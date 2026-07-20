"""Wires input/board_mapper.py's BoardMapper and input/controller.py's
Controller against a given GameEngine - the input-layer half of app.py's
build_game, factored out so it can be constructed (and tested) on its own,
without also constructing a GameEngine/RuleEngine/RealTimeArbiter.
"""

from typing import Tuple

from display_config import CELL_SIZE
from input.board_mapper import BoardMapper
from input.controller import Controller


def build_controller(
    game_engine, width: int, height: int, board_offset_x: int = 0, cell_size: int = CELL_SIZE
) -> Tuple[Controller, BoardMapper]:
    board_mapper = BoardMapper(width=width, height=height, cell_size=cell_size, board_offset_x=board_offset_x)
    controller = Controller(game_engine=game_engine)
    return controller, board_mapper
