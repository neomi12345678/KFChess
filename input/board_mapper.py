from typing import Optional

from config import CELL_SIZE
from model.position import Position


class BoardMapper:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height

    # Returns None for clicks outside the board, letting the caller treat
    # them as "no cell" rather than special-casing bounds everywhere.
    def pixel_to_cell(self, x: int, y: int) -> Optional[Position]:
        if x < 0 or y < 0:
            return None

        row = y // CELL_SIZE
        col = x // CELL_SIZE

        if row < 0 or row >= self.height or col < 0 or col >= self.width:
            return None

        return Position(row, col)
