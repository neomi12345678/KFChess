"""Watches the game from the outside instead of living in
engine.game_engine.GameEngine's move/jump pipeline itself - GameEngine
notifies these (see GameEngine.add_observer), and view/renderer.py reads
their accumulated state back at its own pace, once per frame. Neither
observer here can slow down or block a move/jump request.

Lives under events/, not view/: move-logging and score-keeping are
derived application state, not rendering - view/renderer.py is just one
reader of what accumulates here, so this stays a peer of view/, not a
submodule of it.
"""

from dataclasses import dataclass
from typing import Dict, List

from boardio.algebraic_notation import jump_notation, move_notation
from model.game_state import ArrivalEvent, GameObserver, MoveLoggedEvent
from model.piece import PIECE_VALUES
from model.position import Position


# Display-ready line for the moves-log panel (view/renderer.py) - as
# opposed to model.game_state.MoveLoggedEvent, which carries raw facts with
# no notion of "notation" at all. This type, and the algebraic-notation
# conversion below, are what turn those facts into text - a purely
# view-layer concern GameEngine itself never touches.
#
# Not frozen, unlike MoveLoggedEvent/ArrivalEvent: a move's entry is
# appended to the log immediately (at request time, so the log's own
# ordering/timing keeps matching when the player actually acted, not
# whenever a piece happens to finish crossing the board), but its notation
# text is still only a guess until the piece actually arrives - see
# _PendingMove/on_arrival below. Patching notation in place, instead of
# replacing the entry, is what lets that correction reach view/renderer.py
# without disturbing this entry's position or timestamp in the list.
@dataclass
class MoveLogEntry:
    color: str
    notation: str
    elapsed_ms: int


# A still-unconfirmed move-log entry, tracked by the mover's own piece id
# from the moment on_move_logged reports it until the moment its actual
# outcome is known. kind/source are kept from the original request, not
# re-read off the piece later: a pawn reaching the last rank is promoted
# (see RealTimeArbiter._resolve_arrival's promotion_rule.promote call)
# before its ArrivalEvent is even built, so piece.kind by then may already
# read "queen" - notation has to stay "d8", not "Qd8", the same as it
# would if this were still request-time.
@dataclass(frozen=True)
class _PendingMove:
    entry: MoveLogEntry
    kind: str
    source: Position


class MoveLogObserver(GameObserver):
    # board_height is fixed for the lifetime of a game, so it's supplied
    # once here rather than threaded through every on_move_logged call.
    def __init__(self, board_height: int):
        self._board_height = board_height
        self._entries_by_color: Dict[str, List[MoveLogEntry]] = {}
        self._pending_by_piece_id: Dict[str, _PendingMove] = {}

    def on_move_logged(self, event: MoveLoggedEvent) -> None:
        notation = (
            jump_notation(event.kind, event.source, self._board_height)
            if event.is_jump
            else move_notation(event.kind, event.source, event.destination, self._board_height, event.is_capture)
        )
        entry = MoveLogEntry(color=event.color, notation=notation, elapsed_ms=event.elapsed_ms)
        self._entries_by_color.setdefault(event.color, []).append(entry)

        # A jump's notation is already final the instant it's requested -
        # position and kind never change, and a jump is never a capture
        # (see GameEngine.request_jump) - so only a move needs tracking
        # here. A move can still turn out differently once it actually
        # arrives: route_planner.plan_route can shorten it before it even
        # starts, and RealTimeArbiter._intercept_motion can shorten or
        # upgrade it to a capture mid-flight - either leaves this notation
        # guess stale until on_arrival below corrects it.
        if not event.is_jump:
            self._pending_by_piece_id[event.piece_id] = _PendingMove(entry=entry, kind=event.kind, source=event.source)

    # Reconciles a pending move's logged guess against what actually
    # happened, using the same ArrivalEvent stream ScoreObserver.on_arrival
    # already relies on for the same reason (see its own docstring) - ties
    # this purely to piece identity, never to board position, so a route
    # conflict/interception that changes where a piece actually lands is
    # still matched back to the right entry.
    def on_arrival(self, event: ArrivalEvent) -> None:
        pending = self._pending_by_piece_id.pop(event.piece.id, None)
        if pending is not None:
            pending.entry.notation = move_notation(
                pending.kind,
                pending.source,
                event.piece.cell,
                self._board_height,
                is_capture=event.captured_piece is not None,
            )

        if event.captured_piece is None:
            return

        # The captured piece's own move (not event.piece's - see
        # ScoreObserver.on_arrival's docstring for the same event.piece-
        # is-the-survivor distinction) is only still pending here if it was
        # captured before ever arriving anywhere - RealTimeArbiter's
        # reversed-capture defense (an airborne piece surviving and eating
        # the attacker mid-flight - see _resolve_arrival) or a piece caught
        # mid-flight by a third piece's own earlier arrival (see
        # _clear_pending_motion's docstring). Either way, that move never
        # actually happened - drop the placeholder line instead of leaving
        # a move on display that was never completed. A piece already
        # standing still (or already resolved its own, separate move
        # earlier) was never pending to begin with, so this is a no-op for
        # every ordinary capture.
        victim_pending = self._pending_by_piece_id.pop(event.captured_piece.id, None)
        if victim_pending is not None:
            entries = self._entries_by_color[victim_pending.entry.color]
            entries[:] = [entry for entry in entries if entry is not victim_pending.entry]

    def entries_for(self, color: str) -> List[MoveLogEntry]:
        return list(self._entries_by_color.get(color, []))


class ScoreObserver(GameObserver):
    def __init__(self):
        self._score_by_color: Dict[str, int] = {}

    # Credits whichever color GameEngine's ArrivalEvent says actually did
    # the capturing - event.piece, not the mover that requested the motion,
    # since a reversed capture (an airborne defender surviving and eating
    # the attacker instead - see real_time_arbiter._resolve_arrival) credits
    # the defender, not whoever clicked to move.
    def on_arrival(self, event: ArrivalEvent) -> None:
        if event.captured_piece is None:
            return

        color = event.piece.color
        self._score_by_color[color] = self.score_for(color) + PIECE_VALUES[event.captured_piece.kind]

    def score_for(self, color: str) -> int:
        return self._score_by_color.get(color, 0)
