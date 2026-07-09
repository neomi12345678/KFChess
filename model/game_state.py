from dataclasses import dataclass

from model.board import Board


@dataclass
class GameState:
    board: Board
