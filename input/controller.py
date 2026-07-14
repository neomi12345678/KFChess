from dataclasses import dataclass
from typing import Optional

from input.board_mapper import BoardMapper
from model.board import BoardRepresentation
from model.piece import is_selectable
from model.position import Position


@dataclass
class ControllerResult:
    selected: Optional[Position]
    move_requested: bool


class Controller:
    def __init__(self, board: BoardRepresentation, board_mapper: BoardMapper, game_engine):
        self._board = board
        self._board_mapper = board_mapper
        self._game_engine = game_engine
        self.selected: Optional[Position] = None

    def click(self, x: int, y: int) -> ControllerResult:
        cell = self._board_mapper.pixel_to_cell(x, y)

        if cell is None:
            self.selected = None
            return ControllerResult(selected=None, move_requested=False)

        if self.selected is None:
            if self._board.get_piece(cell) is not None:
                self.selected = cell
            return ControllerResult(selected=self.selected, move_requested=False)

        # Switch selection to a same-color piece instead of attempting an
        # always-illegal move against it - unless it's mid-motion (see
        # model/piece.py's is_selectable, the same table-driven state check
        # GameEngine/RealTimeArbiter use for whether an action may start).
        clicked_piece = self._board.get_piece(cell)
        selected_piece = self._board.get_piece(self.selected)
        if clicked_piece is not None and selected_piece is not None and clicked_piece.color == selected_piece.color:
            if is_selectable(clicked_piece.state):
                self.selected = cell
            return ControllerResult(selected=self.selected, move_requested=False)

        source = self.selected
        self.selected = None
        self._game_engine.request_move(source, cell)
        return ControllerResult(selected=None, move_requested=True)

    def jump(self, x: int, y: int):
        # Jump is single-click, not click/click select-then-target - clear
        # any leftover selection so it doesn't hijack the next click as a move.
        self.selected = None
        cell = self._board_mapper.pixel_to_cell(x, y)
        if cell is None:
            return None
        return self._game_engine.request_jump(cell)
