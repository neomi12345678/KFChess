from typing import List, Optional

import piece_config
from config import (
    AIRBORNE_BASE_DURATION_MS,
    AIRBORNE_DURATION_MULTIPLIER,
    LONG_REST_BASE_DURATION_MS,
    REST_DURATION_MULTIPLIER,
    SHORT_REST_BASE_DURATION_MS,
)
from model.board import BoardRepresentation
from model.game_state import ArrivalEvent
from model.piece import (
    AIRBORNE,
    CAPTURED,
    IDLE,
    LONG_REST,
    MOVING,
    PieceRepresentation,
    SHORT_REST,
    STATE_FOLDER,
    jump_availability,
    move_availability,
)
from model.position import Position
from realtime import route_planner
from physics.motion import Motion, TimedState
from realtime.route_planner import RoutePlan
from rules.rule_engine import LastRankPromotion, PromotionRule


class RealTimeArbiter:
    def __init__(self, board: BoardRepresentation, promotion_rule: Optional[PromotionRule] = None):
        self._board = board
        self._promotion_rule = promotion_rule if promotion_rule is not None else LastRankPromotion()
        self._active_motions: List[Motion] = []
        self._airborne_states: List[TimedState] = []
        self._short_rests: List[TimedState] = []
        self._long_rests: List[TimedState] = []

    def has_active_motion(self) -> bool:
        return len(self._active_motions) > 0

    def get_active_motions(self) -> List[Motion]:
        return list(self._active_motions)

    def get_airborne_pieces(self) -> List[PieceRepresentation]:
        return [airborne.piece for airborne in self._airborne_states]

    # short_rest/long_rest are real piece.state values, not a separate
    # flag, so this is just a state check.
    def is_in_cooldown(self, piece: PieceRepresentation) -> bool:
        return piece.state in (SHORT_REST, LONG_REST)

    # True if the move would be altered at all by an in-flight motion -
    # blocked outright, or truncated short of a same-color race.
    def has_route_conflict(self, piece: PieceRepresentation, source: Position, destination: Position) -> bool:
        plan = self.plan_route(piece, source, destination)
        return plan.is_blocked or plan.destination != destination

    # Whoever is already moving has right of way - see route_planner.plan_route.
    def plan_route(self, piece: PieceRepresentation, source: Position, destination: Position) -> RoutePlan:
        return route_planner.plan_route(self._active_motions, piece, source, destination)

    def start_motion(self, piece: PieceRepresentation, source: Position, destination: Position) -> bool:
        if not move_availability(piece.state).allowed:
            return False

        plan = self.plan_route(piece, source, destination)
        if plan.is_blocked:
            return False

        self._active_motions.append(Motion(piece=piece, source=source, destination=plan.destination))
        piece.state = MOVING
        return True

    def start_jump(self, piece: PieceRepresentation) -> bool:
        if not jump_availability(piece.state).allowed:
            return False

        duration_ms = round(AIRBORNE_BASE_DURATION_MS * AIRBORNE_DURATION_MULTIPLIER)
        self._airborne_states.append(TimedState(piece=piece, duration_ms=duration_ms))
        piece.state = AIRBORNE
        return True

    def advance_time(self, ms: int) -> List[ArrivalEvent]:
        events: List[ArrivalEvent] = []
        completed_motions: List[Motion] = []

        # Existing rests age first, before this tick can start any new ones
        # below - a rest that starts this tick shouldn't also be aged by
        # this same tick's ms.
        self._short_rests = self._advance_rests(self._short_rests, ms, STATE_FOLDER[SHORT_REST])
        self._long_rests = self._advance_rests(self._long_rests, ms, STATE_FOLDER[LONG_REST])

        for motion in self._active_motions:
            motion.elapsed_ms += ms
            if motion.is_complete():
                completed_motions.append(motion)

        # Resolve arrivals before expiring airborne protection below, so a
        # piece landing exactly as its jump window ends is still defended.
        for motion in completed_motions:
            # Already captured by a different motion resolved earlier this
            # same tick - resolving it again would double-remove or
            # resurrect it at a destination it never reached.
            if motion.piece.state != MOVING:
                continue
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
                self._enter_state(airborne.piece, self._next_state_folder(airborne.piece, STATE_FOLDER[AIRBORNE]))

        return events

    # next_state_when_finished lives in the piece's own config.json, not
    # hardcoded here, so editing the JSON actually changes behavior.
    def _next_state_folder(self, piece: PieceRepresentation, state_folder: str) -> str:
        code = piece_config.piece_code(piece.kind, piece.color)
        return piece_config.load(code, state_folder).next_state_when_finished

    # MOVING/AIRBORNE are only entered via start_motion/start_jump, never
    # as next_state_when_finished, so they're not handled here.
    def _enter_state(self, piece: PieceRepresentation, state_folder: str) -> None:
        if state_folder == STATE_FOLDER[IDLE]:
            piece.state = IDLE
        elif state_folder == STATE_FOLDER[SHORT_REST]:
            piece.state = SHORT_REST
            duration_ms = round(SHORT_REST_BASE_DURATION_MS * REST_DURATION_MULTIPLIER)
            self._short_rests.append(TimedState(piece=piece, duration_ms=duration_ms))
        elif state_folder == STATE_FOLDER[LONG_REST]:
            piece.state = LONG_REST
            duration_ms = round(LONG_REST_BASE_DURATION_MS * REST_DURATION_MULTIPLIER)
            self._long_rests.append(TimedState(piece=piece, duration_ms=duration_ms))
        else:
            raise ValueError(f"unsupported next_state_when_finished: {state_folder!r}")

    def _advance_rests(self, rests: List[TimedState], ms: int, state_folder: str) -> List[TimedState]:
        for rest in rests:
            rest.elapsed_ms += ms

        still_resting = []
        for rest in rests:
            if rest.is_expired():
                self._enter_state(rest.piece, self._next_state_folder(rest.piece, state_folder))
            else:
                still_resting.append(rest)
        return still_resting

    def _land_airborne_piece(self, piece: PieceRepresentation) -> None:
        self._airborne_states = [
            airborne for airborne in self._airborne_states if airborne.piece.id != piece.id
        ]

    # Resting gives no protection against capture (unlike AIRBORNE) - without
    # this, a stale rest timer would later flip CAPTURED back to IDLE.
    def _clear_pending_rests(self, piece: PieceRepresentation) -> None:
        self._short_rests = [rest for rest in self._short_rests if rest.piece.id != piece.id]
        self._long_rests = [rest for rest in self._long_rests if rest.piece.id != piece.id]

    # A piece stays at its own motion's source cell until arrival, so a
    # faster piece can capture it mid-flight - without this, its stale
    # Motion would later resolve and resurrect it, wiping the real occupant.
    def _clear_pending_motion(self, piece: PieceRepresentation) -> None:
        self._active_motions = [
            motion for motion in self._active_motions if motion.piece.id != piece.id
        ]

    def _resolve_arrival(self, motion: Motion) -> ArrivalEvent:
        defender = self._board.get_piece(motion.destination)

        # Reversed capture: an airborne enemy defender survives and captures
        # the arriving piece instead of being captured itself. A same-color
        # airborne defender is not an enemy to repel - it falls through to
        # the same-color race branch below instead. A successful defense
        # goes straight back to IDLE, not short_rest - defending doesn't
        # tire a piece the way completing a jump on its own does.
        if defender is not None and defender.state == AIRBORNE and defender.color != motion.piece.color:
            self._board.remove_piece(motion.source)
            motion.piece.state = CAPTURED
            defender.state = IDLE
            self._land_airborne_piece(defender)
            return ArrivalEvent(piece=defender, captured_piece=motion.piece)

        # A same-color piece won a race to this cell since this motion
        # started - stop short instead of overwriting a teammate. It still
        # completed a motion, so it still earns a long_rest.
        if defender is not None and defender.color == motion.piece.color:
            fallback = route_planner.retreat_cell(self._board, motion.source, motion.destination)
            self._board.remove_piece(motion.source)
            self._board.add_piece(fallback, motion.piece)
            self._enter_state(motion.piece, self._next_state_folder(motion.piece, STATE_FOLDER[MOVING]))
            return ArrivalEvent(piece=motion.piece, captured_piece=None)

        captured_piece = defender
        self._board.remove_piece(motion.source)

        if captured_piece is not None:
            self._board.remove_piece(motion.destination)
            captured_piece.state = CAPTURED
            self._clear_pending_rests(captured_piece)
            self._clear_pending_motion(captured_piece)

        self._board.add_piece(motion.destination, motion.piece)
        # Promote before starting the rest, so a pawn reaching the last rank
        # earns its new kind's own long_rest timing, not the pawn's.
        self._promotion_rule.promote(motion.piece, self._board.height)
        self._enter_state(motion.piece, self._next_state_folder(motion.piece, "move"))

        return ArrivalEvent(piece=motion.piece, captured_piece=captured_piece)
