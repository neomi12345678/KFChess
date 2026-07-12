from dataclasses import dataclass
from typing import List, Optional

from model.board import Board
from model.piece import AIRBORNE, CAPTURED, IDLE, MOVING, PAWN, Piece, QUEEN, WHITE
from model.position import Position
from realtime.motion import Airborne, Motion, compute_path

PROMOTION_KIND = QUEEN


@dataclass
class ArrivalEvent:
    piece: Piece
    captured_piece: Optional[Piece]


class RealTimeArbiter:
    def __init__(self, board: Board):
        self._board = board
        self._active_motions: List[Motion] = []
        self._airborne_states: List[Airborne] = []

    def has_active_motion(self) -> bool:
        return len(self._active_motions) > 0

    def get_active_motions(self) -> List[Motion]:
        return list(self._active_motions)

    def get_airborne_pieces(self) -> List[Piece]:
        return [airborne.piece for airborne in self._airborne_states]

    def has_route_conflict(self, source: Position, destination: Position) -> bool:
        requested_path = set(compute_path(source, destination))
        return any(requested_path.intersection(motion.path()) for motion in self._active_motions)

    def start_motion(self, piece: Piece, source: Position, destination: Position) -> None:
        self._active_motions.append(Motion(piece=piece, source=source, destination=destination))
        piece.state = MOVING

    def start_jump(self, piece: Piece) -> bool:
        if piece.state != IDLE:
            return False

        self._airborne_states.append(Airborne(piece=piece))
        piece.state = AIRBORNE
        return True

    def advance_time(self, ms: int) -> List[ArrivalEvent]:
        events: List[ArrivalEvent] = []
        completed_motions: List[Motion] = []

        for motion in self._active_motions:
            motion.elapsed_ms += ms
            if motion.is_complete():
                completed_motions.append(motion)

        for motion in completed_motions:
            self._active_motions.remove(motion)
            events.append(self._resolve_arrival(motion))

        expired_airborne_states = []
        for airborne in self._airborne_states:
            airborne.elapsed_ms += ms
            if airborne.is_expired():
                expired_airborne_states.append(airborne)

        for airborne in expired_airborne_states:
            self._airborne_states.remove(airborne)
            if airborne.piece.state == AIRBORNE:
                airborne.piece.state = IDLE

        return events

    def _land_airborne_piece(self, piece: Piece) -> None:
        self._airborne_states = [
            airborne for airborne in self._airborne_states if airborne.piece is not piece
        ]

    def _resolve_arrival(self, motion: Motion) -> ArrivalEvent:
        defender = self._board.get_piece(motion.destination)

        if defender is not None and defender.state == AIRBORNE:
            self._board.remove_piece(motion.source)
            motion.piece.state = CAPTURED
            defender.state = IDLE
            self._land_airborne_piece(defender)
            return ArrivalEvent(piece=defender, captured_piece=motion.piece)

        captured_piece = defender
        self._board.remove_piece(motion.source)

        if captured_piece is not None:
            self._board.remove_piece(motion.destination)
            captured_piece.state = CAPTURED

        self._board.add_piece(motion.destination, motion.piece)
        motion.piece.state = IDLE
        self._maybe_promote(motion.piece)

        return ArrivalEvent(piece=motion.piece, captured_piece=captured_piece)

    def _maybe_promote(self, piece: Piece) -> None:
        if piece.kind != PAWN:
            return

        last_rank = 0 if piece.color == WHITE else self._board.height - 1
        if piece.cell.row == last_rank:
            piece.kind = PROMOTION_KIND
