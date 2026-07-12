from dataclasses import dataclass
from typing import List, Optional

from model.board import BoardRepresentation
from model.piece import AIRBORNE, CAPTURED, IDLE, MOVING, Piece
from model.position import Position
from realtime.motion import Airborne, Motion, Trajectory, is_straight_line, motion_duration_ms, trajectories_collide
from rules.rule_engine import LastRankPromotion, PromotionRule


@dataclass
class ArrivalEvent:
    piece: Piece
    captured_piece: Optional[Piece]


class RealTimeArbiter:
    def __init__(self, board: BoardRepresentation, promotion_rule: Optional[PromotionRule] = None):
        self._board = board
        self._promotion_rule = promotion_rule if promotion_rule is not None else LastRankPromotion()
        self._active_motions: List[Motion] = []
        self._airborne_states: List[Airborne] = []

    def has_active_motion(self) -> bool:
        return len(self._active_motions) > 0

    def get_active_motions(self) -> List[Motion]:
        return list(self._active_motions)

    def get_airborne_pieces(self) -> List[Piece]:
        return [airborne.piece for airborne in self._airborne_states]

    # True if the requested move would put this piece at the same point at
    # the same instant as an already in-flight motion - a continuous-time
    # check, not just "do the paths cross the same grid cell": two paths
    # that cross in space but at different times are not a conflict.
    # Knight-shaped moves (not a straight line) have no continuous path to
    # collide along and are exempt on either side, treated purely as a
    # jump from source straight to destination.
    def has_route_conflict(self, source: Position, destination: Position) -> bool:
        if not is_straight_line(source, destination):
            return False

        requested = Trajectory(source, destination, motion_duration_ms(source, destination))

        for motion in self._active_motions:
            if not is_straight_line(motion.source, motion.destination):
                continue
            in_flight = Trajectory(
                motion.source, motion.destination, motion.duration_ms, start_offset_ms=-motion.elapsed_ms
            )
            if trajectories_collide(in_flight, requested):
                return True

        return False

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

        # Resolve arrivals before expiring airborne protection below, so a
        # piece landing exactly as its jump window ends is still defended.
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
            # A successful defense already reset this piece to IDLE and
            # dropped it from the list, so it won't be expired twice.
            if airborne.piece.state == AIRBORNE:
                airborne.piece.state = IDLE

        return events

    def _land_airborne_piece(self, piece: Piece) -> None:
        self._airborne_states = [
            airborne for airborne in self._airborne_states if airborne.piece is not piece
        ]

    def _resolve_arrival(self, motion: Motion) -> ArrivalEvent:
        defender = self._board.get_piece(motion.destination)

        # Reversed capture: an airborne defender survives and captures the
        # arriving piece instead of being captured itself.
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
        self._promotion_rule.promote(motion.piece, self._board.height)

        return ArrivalEvent(piece=motion.piece, captured_piece=captured_piece)
