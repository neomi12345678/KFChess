from dataclasses import dataclass

from kungfu_chess.model.board import Board


@dataclass
class GameState:
    board: Board
