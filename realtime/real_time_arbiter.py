from dataclasses import dataclass
from typing import List, Optional

from model.board import BoardRepresentation
from model.piece import AIRBORNE, CAPTURED, IDLE, MOVING, Piece
from model.position import Position
from realtime import route_planner
from realtime.motion import Airborne, Cooldown, Motion
from realtime.route_planner import RoutePlan
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
        self._cooldowns: List[Cooldown] = []

    def has_active_motion(self) -> bool:
        return len(self._active_motions) > 0

    def get_active_motions(self) -> List[Motion]:
        return list(self._active_motions)

    def get_airborne_pieces(self) -> List[Piece]:
        return [airborne.piece for airborne in self._airborne_states]

    def is_in_cooldown(self, piece: Piece) -> bool:
        return any(cooldown.piece is piece for cooldown in self._cooldowns)

    # True if the move would be altered at all by an in-flight motion -
    # blocked, truncated, or turned into a mid-flight capture.
    def has_route_conflict(self, piece: Piece, source: Position, destination: Position) -> bool:
        plan = self.plan_route(piece, source, destination)
        return plan.is_blocked or plan.destination != destination

    # Only the new mover is ever shortened. Different colors capture at the
    # meeting cell; same color stops one cell short of it.
    def plan_route(self, piece: Piece, source: Position, destination: Position) -> RoutePlan:
        return route_planner.plan_route(self._active_motions, piece, source, destination)

    def start_motion(self, piece: Piece, source: Position, destination: Position) -> bool:
        if piece.state != IDLE or self.is_in_cooldown(piece):
            return False

        plan = self.plan_route(piece, source, destination)
        if plan.is_blocked:
            return False

        self._active_motions.append(
            Motion(piece=piece, source=source, destination=plan.destination, capture_target=plan.capture_target)
        )
        piece.state = MOVING
        return True

    def start_jump(self, piece: Piece) -> bool:
        if piece.state != IDLE or self.is_in_cooldown(piece):
            return False

        self._airborne_states.append(Airborne(piece=piece))
        piece.state = AIRBORNE
        return True

    def advance_time(self, ms: int) -> List[ArrivalEvent]:
        events: List[ArrivalEvent] = []
        completed_motions: List[Motion] = []

        # Existing cooldowns age first, before this tick can start any new
        # ones below - a cooldown that starts this tick shouldn't also be
        # aged by this same tick's ms.
        self._advance_cooldowns(ms)

        for motion in self._active_motions:
            motion.elapsed_ms += ms
            if motion.is_complete():
                completed_motions.append(motion)

        # Resolve arrivals before expiring airborne protection below, so a
        # piece landing exactly as its jump window ends is still defended.
        # Captures go first: if a mid-flight capture's victim also happens
        # to complete its own full motion this same tick, the victim must
        # be cancelled before its "arrival" is processed - otherwise it
        # lands safely first and the capture then collides with it.
        completed_motions.sort(key=lambda motion: motion.capture_target is None)
        for motion in completed_motions:
            # A mid-flight capture resolved earlier this batch may have
            # already cancelled this motion (it was the victim).
            if motion not in self._active_motions:
                continue
            self._active_motions.remove(motion)
            event = self._resolve_arrival(motion)
            events.append(event)
            self._start_cooldown(event.piece)

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
                self._start_cooldown(airborne.piece)

        return events

    def _start_cooldown(self, piece: Piece) -> None:
        self._cooldowns.append(Cooldown(piece=piece))

    def _advance_cooldowns(self, ms: int) -> None:
        for cooldown in self._cooldowns:
            cooldown.elapsed_ms += ms
        self._cooldowns = [cooldown for cooldown in self._cooldowns if not cooldown.is_expired()]

    def _land_airborne_piece(self, piece: Piece) -> None:
        self._airborne_states = [
            airborne for airborne in self._airborne_states if airborne.piece is not piece
        ]

    # Cancels a piece's own motion because it was just captured mid-flight -
    # it never reaches the board at any cell but the one it started from.
    def _cancel_motion(self, piece: Piece) -> None:
        for motion in self._active_motions:
            if motion.piece is piece:
                self._active_motions.remove(motion)
                self._board.remove_piece(motion.source)
                break

    def _resolve_arrival(self, motion: Motion) -> ArrivalEvent:
        # Truncated to exactly where it meets an opposing piece head-on -
        # that piece is captured in transit.
        if motion.capture_target is not None:
            self._cancel_motion(motion.capture_target)
            motion.capture_target.state = CAPTURED
            self._board.remove_piece(motion.source)
            self._board.add_piece(motion.destination, motion.piece)
            motion.piece.state = IDLE
            self._promotion_rule.promote(motion.piece, self._board.height)
            return ArrivalEvent(piece=motion.piece, captured_piece=motion.capture_target)

        defender = self._board.get_piece(motion.destination)

        # Reversed capture: an airborne defender survives and captures the
        # arriving piece instead of being captured itself.
        if defender is not None and defender.state == AIRBORNE:
            self._board.remove_piece(motion.source)
            motion.piece.state = CAPTURED
            defender.state = IDLE
            self._land_airborne_piece(defender)
            return ArrivalEvent(piece=defender, captured_piece=motion.piece)

        # A same-color piece won a race to this cell since this motion
        # started - stop short instead of overwriting a teammate.
        if defender is not None and defender.color == motion.piece.color:
            fallback = route_planner.cell_before(motion.source, motion.destination)
            self._board.remove_piece(motion.source)
            self._board.add_piece(fallback, motion.piece)
            motion.piece.state = IDLE
            return ArrivalEvent(piece=motion.piece, captured_piece=None)

        captured_piece = defender
        self._board.remove_piece(motion.source)

        if captured_piece is not None:
            self._board.remove_piece(motion.destination)
            captured_piece.state = CAPTURED

        self._board.add_piece(motion.destination, motion.piece)
        motion.piece.state = IDLE
        self._promotion_rule.promote(motion.piece, self._board.height)

        return ArrivalEvent(piece=motion.piece, captured_piece=captured_piece)
