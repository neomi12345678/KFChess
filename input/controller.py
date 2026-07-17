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
    "are these two cells the same color?", "is this still the same piece?")
    is an explicit call to GameEngine (the single gate), so selection
    permission has exactly one source of truth, shared with GameEngine's own
    request_move/request_jump checks - see GameEngine.can_select.

    Selection is tracked by cell *and* piece id (see _selected_piece_id) -
    real wall-clock time passes between two clicks in interactive play, so
    the piece at the selected cell on the first click may not be the piece
    still there on the second: it could have been captured, with a
    different piece's motion since landing on that same cell."""

    def __init__(self, game_engine):
        self._game_engine = game_engine
        self.selected: Optional[Position] = None
        # Real wall-clock time passes between two clicks in interactive
        # play - the piece originally selected can be captured, or its cell
        # taken over by a different piece's motion landing there, before the
        # second click arrives. self.selected is only ever a cell; this is
        # what lets click() tell "still the same piece" from "something
        # else is here now" (see the identity check below).
        self._selected_piece_id: Optional[str] = None

    def click(self, cell: Optional[Position]) -> ControllerResult:
        if cell is None:
            self._clear_selection()
            return ControllerResult(selected=None, move_requested=False)

        if self.selected is None:
            self._select_if_possible(cell)
            return ControllerResult(selected=self.selected, move_requested=False)

        # The selected cell's occupant may no longer be the piece that was
        # selected - stale selection state is cleared rather than acted on,
        # the same way an out-of-board click already clears it above.
        if self._game_engine.piece_id_at(self.selected) != self._selected_piece_id:
            self._clear_selection()
            return ControllerResult(selected=None, move_requested=False)

        # Switch selection to a same-color piece instead of attempting an
        # always-illegal move against it - unless it's currently unselectable
        # (mid-motion, airborne, or in cooldown - see GameEngine.can_select).
        if self._game_engine.is_same_color(self.selected, cell):
            self._select_if_possible(cell)
            return ControllerResult(selected=self.selected, move_requested=False)

        source = self.selected
        self._clear_selection()
        self._game_engine.request_move(source, cell)
        return ControllerResult(selected=None, move_requested=True)

    def jump(self, cell: Optional[Position]):
        # Jump is single-click, not click/click select-then-target - clear
        # any leftover selection so it doesn't hijack the next click as a move.
        self._clear_selection()
        if cell is None:
            return None
        return self._game_engine.request_jump(cell)

    def _select_if_possible(self, cell: Position) -> None:
        if self._game_engine.can_select(cell):
            self.selected = cell
            self._selected_piece_id = self._game_engine.piece_id_at(cell)

    def _clear_selection(self) -> None:
        self.selected = None
        self._selected_piece_id = None
