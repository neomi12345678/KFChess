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


# Display-ready line for the moves-log panel (view/renderer.py) - as
# opposed to model.game_state.MoveLoggedEvent, which carries raw facts with
# no notion of "notation" at all. This type, and the algebraic-notation
# conversion below, are what turn those facts into text - a purely
# view-layer concern GameEngine itself never touches.
@dataclass(frozen=True)
class MoveLogEntry:
    color: str
    notation: str
    elapsed_ms: int


class MoveLogObserver(GameObserver):
    # board_height is fixed for the lifetime of a game, so it's supplied
    # once here rather than threaded through every on_move_logged call.
    def __init__(self, board_height: int):
        self._board_height = board_height
        self._entries_by_color: Dict[str, List[MoveLogEntry]] = {}

    def on_move_logged(self, event: MoveLoggedEvent) -> None:
        notation = (
            jump_notation(event.kind, event.source, self._board_height)
            if event.is_jump
            else move_notation(event.kind, event.source, event.destination, self._board_height, event.is_capture)
        )
        entry = MoveLogEntry(color=event.color, notation=notation, elapsed_ms=event.elapsed_ms)
        self._entries_by_color.setdefault(event.color, []).append(entry)

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
