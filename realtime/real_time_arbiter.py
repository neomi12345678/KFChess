from typing import List, Optional

from model.board import BoardRepresentation
from model.game_state import ArrivalEvent
from model.piece import AIRBORNE, CAPTURED, IDLE, MOVING, PieceRepresentation
from model.position import Position
from realtime import route_planner
from realtime.motion import Airborne, Cooldown, Motion
from realtime.route_planner import RoutePlan
from rules.rule_engine import LastRankPromotion, PromotionRule


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

    def get_airborne_pieces(self) -> List[PieceRepresentation]:
        return [airborne.piece for airborne in self._airborne_states]

    def is_in_cooldown(self, piece: PieceRepresentation) -> bool:
        return any(cooldown.piece.id == piece.id for cooldown in self._cooldowns)

    # True if the move would be altered at all by an in-flight motion -
    # blocked outright, or truncated short of a same-color race.
    def has_route_conflict(self, piece: PieceRepresentation, source: Position, destination: Position) -> bool:
        plan = self.plan_route(piece, source, destination)
        return plan.is_blocked or plan.destination != destination

    # Whoever is already moving has right of way - see route_planner.plan_route.
    def plan_route(self, piece: PieceRepresentation, source: Position, destination: Position) -> RoutePlan:
        return route_planner.plan_route(self._active_motions, piece, source, destination)

    def start_motion(self, piece: PieceRepresentation, source: Position, destination: Position) -> bool:
        if piece.state != IDLE or self.is_in_cooldown(piece):
            return False

        plan = self.plan_route(piece, source, destination)
        if plan.is_blocked:
            return False

        self._active_motions.append(Motion(piece=piece, source=source, destination=plan.destination))
        piece.state = MOVING
        return True

    def start_jump(self, piece: PieceRepresentation) -> bool:
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
        for motion in completed_motions:
            self._active_motions.remove(motion)
            event = self._resolve_arrival(motion)
            events.append(event)

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

    def _start_cooldown(self, piece: PieceRepresentation) -> None:
        self._cooldowns.append(Cooldown(piece=piece))

    def _advance_cooldowns(self, ms: int) -> None:
        for cooldown in self._cooldowns:
            cooldown.elapsed_ms += ms
        self._cooldowns = [cooldown for cooldown in self._cooldowns if not cooldown.is_expired()]

    def _land_airborne_piece(self, piece: PieceRepresentation) -> None:
        self._airborne_states = [
            airborne for airborne in self._airborne_states if airborne.piece.id != piece.id
        ]

    def _resolve_arrival(self, motion: Motion) -> ArrivalEvent:
        defender = self._board.get_piece(motion.destination)

        # Reversed capture: an airborne enemy defender survives and captures
        # the arriving piece instead of being captured itself. A same-color
        # airborne defender is not an enemy to repel - it falls through to
        # the same-color race branch below instead.
        if defender is not None and defender.state == AIRBORNE and defender.color != motion.piece.color:
            self._board.remove_piece(motion.source)
            motion.piece.state = CAPTURED
            defender.state = IDLE
            self._land_airborne_piece(defender)
            return ArrivalEvent(piece=defender, captured_piece=motion.piece)

        # A same-color piece won a race to this cell since this motion
        # started - stop short instead of overwriting a teammate.
        if defender is not None and defender.color == motion.piece.color:
            fallback = route_planner.retreat_cell(self._board, motion.source, motion.destination)
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
