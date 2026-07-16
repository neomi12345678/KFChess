from dataclasses import dataclass
from typing import Optional

from model.position import Position


@dataclass
class ControllerResult:
    selected: Optional[Position]
    move_requested: bool


class Controller:
    """Interprets already-resolved board cells and owns selection state
    only - never holds a Board or reads a Piece directly, and never sees a
    pixel: translating a raw click into a cell is input/board_mapper.py's
    job, done by the caller (see app.py's App) before this class is ever
    invoked. Every question about game state ("can this cell be selected?",
    "are these two cells the same color?") is an explicit call to
    GameEngine (the single gate), so selection permission has exactly one
    source of truth, shared with GameEngine's own request_move/request_jump
    checks - see GameEngine.can_select."""

    def __init__(self, game_engine):
        self._game_engine = game_engine
        self.selected: Optional[Position] = None

    def click(self, cell: Optional[Position]) -> ControllerResult:
        if cell is None:
            self.selected = None
            return ControllerResult(selected=None, move_requested=False)

        if self.selected is None:
            if self._game_engine.can_select(cell):
                self.selected = cell
            return ControllerResult(selected=self.selected, move_requested=False)

        # Switch selection to a same-color piece instead of attempting an
        # always-illegal move against it - unless it's currently unselectable
        # (mid-motion, airborne, or in cooldown - see GameEngine.can_select).
        if self._game_engine.is_same_color(self.selected, cell):
            if self._game_engine.can_select(cell):
                self.selected = cell
            return ControllerResult(selected=self.selected, move_requested=False)

        source = self.selected
        self.selected = None
        self._game_engine.request_move(source, cell)
        return ControllerResult(selected=None, move_requested=True)

    def jump(self, cell: Optional[Position]):
        # Jump is single-click, not click/click select-then-target - clear
        # any leftover selection so it doesn't hijack the next click as a move.
        self.selected = None
        if cell is None:
            return None
        return self._game_engine.request_jump(cell)
