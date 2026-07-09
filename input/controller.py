from dataclasses import dataclass
from typing import Optional

from input.board_mapper import BoardMapper
from model.board import Board
from model.position import Position


@dataclass
class ControllerResult:
    selected: Optional[Position]
    move_requested: bool


class Controller:
    def __init__(self, board: Board, board_mapper: BoardMapper, game_engine):
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

        source = self.selected
        self.selected = None
        self._game_engine.request_move(source, cell)
        return ControllerResult(selected=None, move_requested=True)
