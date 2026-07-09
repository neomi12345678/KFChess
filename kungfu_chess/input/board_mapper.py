from typing import Optional

from kungfu_chess.model.position import Position

CELL_SIZE = 100


class BoardMapper:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height

    def pixel_to_cell(self, x: int, y: int) -> Optional[Position]:
        if x < 0 or y < 0:
            return None

        row = y // CELL_SIZE
        col = x // CELL_SIZE

        if row < 0 or row >= self.height or col < 0 or col >= self.width:
            return None

        return Position(row, col)
