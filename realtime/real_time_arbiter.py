from dataclasses import dataclass
from typing import List, Optional, Tuple

from logic_config import (
    AIRBORNE_BASE_DURATION_MS,
    AIRBORNE_DURATION_MULTIPLIER,
    LONG_REST_BASE_DURATION_MS,
    MOVE_CELL_DURATION_MS,
    REST_DURATION_MULTIPLIER,
    SHORT_REST_BASE_DURATION_MS,
)
from model.board import BoardRepresentation
from model.game_state import ArrivalEvent
from model.piece import (
    CAPTURED,
    IDLE,
    MOVING,
    PieceRepresentation,
    jump_availability,
    move_availability,
)
from model.position import Position
from physics.motion import Motion, TimedState
from realtime.route_planner import RoutePlan, plan_route, retreat_cell
from rules.rule_engine import LastRankPromotion, PromotionRule


# A capture scheduled for the future, not resolved the instant it's
# discovered - see _intercept_motion's opposite-color branch. motion keeps
# flying untouched; whatever is standing on `cell` only actually dies once
# motion's own elapsed_ms genuinely reaches it, matching how far its sprite
# has visually gotten instead of vanishing the moment the game logic merely
# predicts the collision.
@dataclass
class _PendingInterception:
    motion: Motion
    cell: Position
    trigger_elapsed_ms: int


class RealTimeArbiter:
    def __init__(self, board: BoardRepresentation, promotion_rule: Optional[PromotionRule] = None):
        self._board = board
        self._promotion_rule = promotion_rule if promotion_rule is not None else LastRankPromotion()
        self._active_motions: List[Motion] = []
        self._airborne_states: List[TimedState] = []
        self._short_rests: List[TimedState] = []
        self._long_rests: List[TimedState] = []
        # Captures resolved synchronously inside start_motion (see
        # blocking_enemy below) - unlike every other capture, there's no
        # advance_time tick to hand the resulting ArrivalEvent back through,
        # so callers (GameEngine.request_move) pull them via
        # take_pending_events() right after calling start_motion.
        self._pending_events: List[ArrivalEvent] = []
        self._pending_interceptions: List[_PendingInterception] = []

    def has_active_motion(self) -> bool:
        return len(self._active_motions) > 0

    def get_active_motions(self) -> List[Motion]:
        return list(self._active_motions)

    def get_airborne_pieces(self) -> List[PieceRepresentation]:
        return [airborne.piece for airborne in self._airborne_states]

    # Airborne/resting are tracked here, out-of-band from piece.state (see
    # model/piece.py) - a piece stays IDLE the whole time it's mid-jump or
    # cooling down; only this arbiter's own bookkeeping knows which.
    def is_airborne(self, piece: PieceRepresentation) -> bool:
        return any(airborne.piece.id == piece.id for airborne in self._airborne_states)

    def is_in_cooldown(self, piece: PieceRepresentation) -> bool:
        return self.is_in_short_rest(piece) or self.is_in_long_rest(piece)

    # Split out of is_in_cooldown() so GameEngine.snapshot() can report
    # which of the two a piece is in (see model.piece.PHASE_SHORT_REST/
    # PHASE_LONG_REST) - move/jump-availability checks only ever need the
    # combined is_in_cooldown() above, never these individually.
    def is_in_short_rest(self, piece: PieceRepresentation) -> bool:
        return any(rest.piece.id == piece.id for rest in self._short_rests)

    def is_in_long_rest(self, piece: PieceRepresentation) -> bool:
        return any(rest.piece.id == piece.id for rest in self._long_rests)

    # Whoever is already moving has right of way - see route_planner.plan_route.
    def plan_route(self, piece: PieceRepresentation, source: Position, destination: Position) -> RoutePlan:
        return plan_route(self._active_motions, piece, source, destination)

    def start_motion(self, piece: PieceRepresentation, source: Position, destination: Position) -> bool:
        if not move_availability(piece.state).allowed:
            return False
        if self.is_airborne(piece) or self.is_in_cooldown(piece):
            return False

        plan = self.plan_route(piece, source, destination)
        if plan.is_blocked:
            if plan.blocking_enemy is not None:
                self._capture_blocked_mover(loser=piece, loser_cell=source, winner=plan.blocking_enemy)
            return False

        self._active_motions.append(Motion(piece=piece, source=source, destination=plan.destination))
        piece.state = MOVING
        return True

    # The already-moving enemy (winner) had right of way over this cell/path
    # first - loser tried to cross it later and loses outright, captured on
    # the spot at its own current cell instead of merely being denied the
    # move. winner's own motion is left completely untouched here - it was
    # never diverted or stopped, so nothing about it needs updating. winner
    # is typically still mid-flight itself at this instant (its own motion
    # hasn't completed yet), so has_landed=False - see ArrivalEvent.
    def _capture_blocked_mover(self, loser: PieceRepresentation, loser_cell: Position, winner: PieceRepresentation) -> None:
        self._board.remove_piece(loser_cell)
        self._mark_captured(loser)
        self._clear_pending_rests(loser)
        self._clear_pending_motion(loser)
        self._pending_events.append(ArrivalEvent(piece=winner, captured_piece=loser, has_landed=False))

    # Drains captures resolved synchronously by start_motion (see
    # _capture_blocked_mover) - called by GameEngine.request_move right
    # after start_motion, regardless of whether it returned True or False,
    # so a capture that happens on an otherwise-rejected request still
    # reaches observers and the win condition the same way any other
    # ArrivalEvent does.
    def take_pending_events(self) -> List[ArrivalEvent]:
        events = self._pending_events
        self._pending_events = []
        return events

    def start_jump(self, piece: PieceRepresentation) -> bool:
        if not jump_availability(piece.state).allowed:
            return False
        if self.is_airborne(piece) or self.is_in_cooldown(piece):
            return False

        duration_ms = round(AIRBORNE_BASE_DURATION_MS * AIRBORNE_DURATION_MULTIPLIER)
        self._airborne_states.append(TimedState(piece=piece, duration_ms=duration_ms))
        # piece.state stays IDLE for the whole jump - "airborne" only ever
        # lives in self._airborne_states (see is_airborne()), never on the
        # piece itself.
        return True

    def advance_time(self, ms: int) -> List[ArrivalEvent]:
        events: List[ArrivalEvent] = []
        completed_motions: List[Motion] = []

        # Existing rests age first, before this tick can start any new ones
        # below - a rest that starts this tick shouldn't also be aged by
        # this same tick's ms.
        self._short_rests = self._advance_rests(self._short_rests, ms)
        self._long_rests = self._advance_rests(self._long_rests, ms)

        for motion in self._active_motions:
            motion.elapsed_ms += ms
            if motion.is_complete():
                completed_motions.append(motion)

        # Multiple motions can complete within one tick - process them in
        # the order they actually finished in real time (not request/
        # insertion order), so a short move that chronologically landed
        # first is already reflected on the board before a still-in-flight
        # longer motion is checked against it (see _completion_offset_ms /
        # _intercept_motions_crossing) - otherwise a single coarse wait()
        # spanning both completions could resolve them in the wrong order
        # and miss an interception a per-frame-sized wait() would have
        # caught correctly.
        completed_motions.sort(key=lambda motion: self._completion_offset_ms(motion, ms))

        # Resolve arrivals before expiring airborne protection below, so a
        # piece landing exactly as its jump window ends is still defended.
        for motion in completed_motions:
            # Already captured by a different motion resolved earlier this
            # same tick - resolving it again would double-remove or
            # resurrect it at a destination it never reached.
            if motion.piece.state != MOVING:
                continue
            self._active_motions.remove(motion)
            completion_offset_ms = self._completion_offset_ms(motion, ms)
            event, landed_cell = self._resolve_arrival(motion)
            events.append(event)
            if landed_cell is not None:
                events.extend(self._intercept_motions_crossing(landed_cell, ms, completion_offset_ms))

        # Anything scheduled above (this tick or an earlier one) whose
        # trigger has now genuinely been reached - checked after this
        # tick's own new obstacles are already scheduled, so a single
        # coarse wait() spanning both "obstacle lands" and "attacker's own
        # flight reaches it" still resolves at the right elapsed_ms instead
        # of missing it until some future call.
        events.extend(self._resolve_due_interceptions())

        expired_airborne_states = []
        for airborne in self._airborne_states:
            airborne.elapsed_ms += ms
            if airborne.is_expired():
                expired_airborne_states.append(airborne)

        for airborne in expired_airborne_states:
            # A successful defense (see _resolve_arrival) already removed
            # this same entry from self._airborne_states above, via
            # _land_airborne_piece - so anything still here genuinely timed
            # out unresolved and always lands into short_rest.
            self._airborne_states.remove(airborne)
            self._start_short_rest(airborne.piece)

        return events

    # A landed move always earns a long_rest, a landed jump always earns a
    # short_rest, and either rest always finishes back at idle - a fixed
    # game-design shape (see logic_config.py's *_BASE_DURATION_MS), never derived
    # from a piece's own animation config. piece.state itself never records
    # short_rest/long_rest; it goes straight back to IDLE, and only
    # is_in_cooldown()'s own bookkeeping below remembers the cooldown.
    def _start_long_rest(self, piece: PieceRepresentation) -> None:
        self._mark_idle(piece)
        duration_ms = round(LONG_REST_BASE_DURATION_MS * REST_DURATION_MULTIPLIER)
        self._long_rests.append(TimedState(piece=piece, duration_ms=duration_ms))

    def _start_short_rest(self, piece: PieceRepresentation) -> None:
        self._mark_idle(piece)
        duration_ms = round(SHORT_REST_BASE_DURATION_MS * REST_DURATION_MULTIPLIER)
        self._short_rests.append(TimedState(piece=piece, duration_ms=duration_ms))

    # The only two places piece.state is ever written after start_motion's
    # own MOVING assignment - every rest, every successful defense, and
    # every capture routes through one of these, so a future addition to
    # any of those call sites can't drift out of sync with the other's
    # bookkeeping (_active_motions/_airborne_states/_short_rests/
    # _long_rests) by simply forgetting to also flip piece.state.
    def _mark_idle(self, piece: PieceRepresentation) -> None:
        piece.state = IDLE

    def _mark_captured(self, piece: PieceRepresentation) -> None:
        piece.state = CAPTURED

    def _advance_rests(self, rests: List[TimedState], ms: int) -> List[TimedState]:
        for rest in rests:
            rest.elapsed_ms += ms
        return [rest for rest in rests if not rest.is_expired()]

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

    # Second element of the return value is whichever cell this call's own
    # add_piece just filled - None for the reversed-airborne-capture branch,
    # which never calls add_piece (the defender never left its own cell).
    # advance_time feeds that cell into _intercept_motions_crossing right
    # after, to catch a still-in-flight motion this new occupant now stands
    # in the way of (see that method's docstring for why request-time
    # plan_route alone can't already cover this).
    def _resolve_arrival(self, motion: Motion) -> Tuple[ArrivalEvent, Optional[Position]]:
        defender = self._board.get_piece(motion.destination)

        # Reversed capture: an airborne enemy defender survives and captures
        # the arriving piece instead of being captured itself. A same-color
        # airborne defender is not an enemy to repel - it falls through to
        # the same-color race branch below instead. A successful defense
        # goes straight back to IDLE, not short_rest - defending doesn't
        # tire a piece the way completing a jump on its own does.
        if defender is not None and self.is_airborne(defender) and defender.color != motion.piece.color:
            self._board.remove_piece(motion.source)
            self._mark_captured(motion.piece)
            self._mark_idle(defender)
            self._land_airborne_piece(defender)
            return ArrivalEvent(piece=defender, captured_piece=motion.piece), None

        # A same-color piece won a race to this cell since this motion
        # started - stop short instead of overwriting a teammate. It still
        # completed a motion, so it still earns a long_rest.
        if defender is not None and defender.color == motion.piece.color:
            fallback = retreat_cell(self._board, motion.source, motion.destination)
            self._board.remove_piece(motion.source)
            self._board.add_piece(fallback, motion.piece)
            self._start_long_rest(motion.piece)
            return ArrivalEvent(piece=motion.piece, captured_piece=None), fallback

        captured_piece = defender
        self._board.remove_piece(motion.source)

        if captured_piece is not None:
            self._board.remove_piece(motion.destination)
            self._mark_captured(captured_piece)
            self._clear_pending_rests(captured_piece)
            self._clear_pending_motion(captured_piece)

        self._board.add_piece(motion.destination, motion.piece)
        # Promote before starting the rest, so a pawn reaching the last rank
        # earns its new kind's own long_rest timing, not the pawn's.
        self._promotion_rule.promote(motion.piece, self._board.height)
        self._start_long_rest(motion.piece)

        return ArrivalEvent(piece=motion.piece, captured_piece=captured_piece), motion.destination

    # How far into the current tick (0..ms) a motion that completes this
    # tick actually finished, in true chronological terms - advance_time
    # bulk-ages every active motion by the whole tick up front, so this is
    # what lets completed_motions be processed in the order they really
    # happened instead of insertion order, and lets
    # _intercept_motions_crossing ask a still-in-flight motion how far it
    # had actually gotten at that instant.
    def _completion_offset_ms(self, motion: Motion, ms: int) -> int:
        elapsed_before_tick = motion.elapsed_ms - ms
        return motion.duration_ms - elapsed_before_tick

    # Closes a gap route_planner.plan_route's request-time check can't see:
    # a motion granted before some other, separately-requested motion even
    # existed has no way to know that motion will later land on one of its
    # own remaining path cells. Called right after each add_piece inside
    # _resolve_arrival (both the same-color-race fallback and the normal-
    # arrival branch) and, recursively, right after _intercept_motion's own
    # same-color fallback add_piece - a domino: an intercepted motion's new
    # resting cell can itself sit on a third motion's remaining path,
    # exactly the same shape of gap this whole mechanism exists to close,
    # just one step removed. Called immediately rather than deferred in
    # every case, so a motion this same tick's own later completions
    # haven't been processed yet is still found, and so an already-
    # intercepted motion is gone from self._active_motions before any
    # later, chronologically-later trigger this same tick can double-hit
    # it.
    #
    # The state guard mirrors advance_time's own "already captured earlier
    # this same tick" guard: list(self._active_motions) is a snapshot taken
    # once at the top of this call, but an earlier iteration's own
    # recursive cascade (via _intercept_motion's domino call below) can
    # already have resolved a *later* entry in that same snapshot before
    # this loop reaches it - without this check, re-processing it would
    # call self._active_motions.remove() on a motion no longer in the list.
    def _intercept_motions_crossing(self, landed_cell: Position, ms: int, completion_offset_ms: int) -> List[ArrivalEvent]:
        events: List[ArrivalEvent] = []
        for motion in list(self._active_motions):
            if motion.piece.state != MOVING:
                continue
            effective_elapsed_ms = motion.elapsed_ms - ms + completion_offset_ms
            if landed_cell in motion.remaining_cells(as_of_elapsed_ms=effective_elapsed_ms):
                events.extend(self._intercept_motion(motion, landed_cell, ms, completion_offset_ms))
        return events

    # The same two outcomes a request-time route conflict already
    # establishes (see route_planner.plan_route), applied after the fact to
    # a motion already granted and mid-flight instead of before
    # start_motion. Same color means it stops one cell short instead of
    # overwriting a teammate, reusing retreat_cell exactly as a normal
    # same-color arrival does - it still counts as having completed a
    # motion, so it still earns a long_rest, and its own new fallback cell
    # is immediately re-checked against every other still-active motion.
    #
    # Opposite color means motion.piece - already flying toward or through
    # this cell before occupant ever landed there - has right of way (see
    # plan_route's own docstring: "whoever is already moving has right of
    # way"), exactly like the request-time equivalent in start_motion's own
    # _capture_blocked_mover. But occupant doesn't die the instant this is
    # merely predicted - it's only genuinely in motion.piece's way once
    # motion.piece's own elapsed_ms actually reaches `cell`, matching where
    # its sprite has really gotten to, not the moment the game logic
    # happens to notice the future collision (which, for a still-distant
    # `cell`, can be far earlier). So this only schedules the capture (see
    # _resolve_due_interceptions, checked every advance_time tick) instead
    # of resolving it here - motion.piece itself is left completely
    # untouched either way, still flying toward its own farther, originally
    # -requested destination, not diverted to settle at `cell`. If `cell`
    # happens to equal motion's own destination, no scheduling is needed at
    # all: _resolve_arrival already checks for (and captures) whatever's
    # standing at a motion's own destination the moment it naturally
    # arrives - the exact same "wait until it's really there" behavior,
    # for free.
    #
    # ms/completion_offset_ms are still threaded through to the same-color
    # branch's own domino - a cascade that branch triggers happens at the
    # exact same simulated instant as the trigger that caused it, not later
    # in the tick.
    def _intercept_motion(self, motion: Motion, cell: Position, ms: int, completion_offset_ms: int) -> List[ArrivalEvent]:
        # landed_cell is always freshly occupied here - either by whatever
        # _resolve_arrival (or this same method's own same-color branch,
        # below) just placed there, immediately before this call - so
        # there's always a real occupant to check against.
        occupant = self._board.get_piece(cell)

        if occupant.color == motion.piece.color:
            self._active_motions.remove(motion)
            fallback = retreat_cell(self._board, motion.source, cell)
            self._board.remove_piece(motion.source)
            self._board.add_piece(fallback, motion.piece)
            self._start_long_rest(motion.piece)
            events = [ArrivalEvent(piece=motion.piece, captured_piece=None)]
            events.extend(self._intercept_motions_crossing(fallback, ms, completion_offset_ms))
            return events

        if cell == motion.destination:
            return []

        self._schedule_interception(motion, cell)
        return []

    def _elapsed_ms_to_reach(self, motion: Motion, cell: Position) -> int:
        cell_index = max(abs(cell.row - motion.source.row), abs(cell.col - motion.source.col))
        return cell_index * MOVE_CELL_DURATION_MS

    def _schedule_interception(self, motion: Motion, cell: Position) -> None:
        trigger_elapsed_ms = self._elapsed_ms_to_reach(motion, cell)
        already_scheduled = any(
            pending.motion is motion and pending.cell == cell for pending in self._pending_interceptions
        )
        if not already_scheduled:
            self._pending_interceptions.append(
                _PendingInterception(motion=motion, cell=cell, trigger_elapsed_ms=trigger_elapsed_ms)
            )

    # Resolves every scheduled interception (see _schedule_interception)
    # whose trigger has actually been reached - called once per
    # advance_time tick, after that same tick's own new obstacles have
    # already had their own chance to schedule, so a single coarse wait()
    # spanning both "obstacle lands" and "attacker's own flight reaches it"
    # still resolves at the right elapsed_ms instead of only catching up on
    # some later tick. Sorted by trigger so a shared cell's earliest claim
    # wins deterministically, same tie-break spirit as completed_motions'
    # own chronological sort.
    def _resolve_due_interceptions(self) -> List[ArrivalEvent]:
        due = sorted(
            (
                pending
                for pending in self._pending_interceptions
                if pending.motion.elapsed_ms >= pending.trigger_elapsed_ms
            ),
            key=lambda pending: pending.trigger_elapsed_ms,
        )
        events: List[ArrivalEvent] = []
        for pending in due:
            self._pending_interceptions.remove(pending)

            # motion.piece was itself captured before ever genuinely
            # reaching `cell` (e.g. run over by an earlier interception, or
            # blocked at request time) - it never actually got there, so
            # there's nothing left to enforce. Landing normally (state
            # IDLE) does NOT cancel this: elapsed_ms already proves motion
            # passed through `cell` before it landed, chronologically
            # earlier than its own arrival regardless of processing order
            # within this tick.
            if pending.motion.piece.state == CAPTURED:
                continue

            occupant = self._board.get_piece(pending.cell)
            if occupant is None or occupant.color == pending.motion.piece.color:
                continue

            self._board.remove_piece(pending.cell)
            self._mark_captured(occupant)
            self._clear_pending_rests(occupant)
            self._clear_pending_motion(occupant)
            events.append(ArrivalEvent(piece=pending.motion.piece, captured_piece=occupant, has_landed=False))
        return events
