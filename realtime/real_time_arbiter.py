from dataclasses import dataclass
from typing import List, Optional

from model.board import Board
from model.piece import AIRBORNE, CAPTURED, IDLE, MOVING, Piece
from model.position import Position
from realtime.motion import Airborne, Motion

PROMOTION_KIND = "Q"


@dataclass
class ArrivalEvent:
    piece: Piece
    captured_piece: Optional[Piece]


class RealTimeArbiter:
    def __init__(self, board: Board):
        self._board = board
        self._active_motion: Optional[Motion] = None
        self._airborne: Optional[Airborne] = None

    def has_active_motion(self) -> bool:
        return self._active_motion is not None

    def get_active_motion(self) -> Optional[Motion]:
        return self._active_motion

    def start_motion(self, piece: Piece, source: Position, destination: Position) -> None:
        self._active_motion = Motion(piece=piece, source=source, destination=destination)
        piece.state = MOVING

    def start_jump(self, piece: Piece) -> bool:
        if piece.state == MOVING:
            return False

        self._airborne = Airborne(piece=piece)
        piece.state = AIRBORNE
        return True

    def advance_time(self, ms: int) -> List[ArrivalEvent]:
        events: List[ArrivalEvent] = []

        if self._active_motion is not None:
            self._active_motion.elapsed_ms += ms

            if self._active_motion.is_complete():
                motion = self._active_motion
                self._active_motion = None
                events.append(self._resolve_arrival(motion))

        if self._airborne is not None:
            self._airborne.elapsed_ms += ms

            if self._airborne.is_expired():
                if self._airborne.piece.state == AIRBORNE:
                    self._airborne.piece.state = IDLE
                self._airborne = None

        return events

    def _resolve_arrival(self, motion: Motion) -> ArrivalEvent:
        defender = self._board.get_piece(motion.destination)

        if defender is not None and defender.state == AIRBORNE:
            self._board.remove_piece(motion.source)
            motion.piece.state = CAPTURED
            defender.state = IDLE
            self._airborne = None
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
        if piece.kind != "P":
            return

        last_rank = 0 if piece.color == "w" else self._board.height - 1
        if piece.cell.row == last_rank:
            piece.kind = PROMOTION_KIND
