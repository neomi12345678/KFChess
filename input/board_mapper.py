from typing import Optional

from config import CELL_SIZE
from model.position import Position


class BoardMapper:
    # cell_size defaults to the app's configured CELL_SIZE, but takes it as
    # a constructor argument rather than reading the config module directly
    # in pixel_to_cell - a caller (or a test) can supply a different value
    # without monkeypatching config.
    def __init__(self, width: int, height: int, cell_size: int = CELL_SIZE):
        self.width = width
        self.height = height
        self.cell_size = cell_size

    # Returns None for clicks outside the board, letting the caller treat
    # them as "no cell" rather than special-casing bounds everywhere.
    def pixel_to_cell(self, x: int, y: int) -> Optional[Position]:
        if x < 0 or y < 0:
            return None

        row = y // self.cell_size
        col = x // self.cell_size

        if row < 0 or row >= self.height or col < 0 or col >= self.width:
            return None

        return Position(row, col)
