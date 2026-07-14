from typing import Optional

from config import CELL_SIZE
from model.position import Position


class BoardMapper:
    # cell_size defaults to the app's configured CELL_SIZE, but takes it as
    # a constructor argument rather than reading the config module directly
    # in pixel_to_cell - a caller (or a test) can supply a different value
    # without monkeypatching config.
    #
    # board_offset_x mirrors graphics.img_canvas.ImgCanvas's own
    # _board_offset_x - when the window has side panels (see config's
    # SIDE_PANEL_WIDTH_PX), the actual board is drawn inset by that many
    # pixels, so raw mouse x has to be shifted back before dividing into
    # columns, or every click lands a whole panel-width off. Defaults to 0
    # so a caller with no panels gets the previous, unshifted behavior.
    def __init__(self, width: int, height: int, cell_size: int = CELL_SIZE, board_offset_x: int = 0):
        self.width = width
        self.height = height
        self.cell_size = cell_size
        self.board_offset_x = board_offset_x

    # Returns None for clicks outside the board, letting the caller treat
    # them as "no cell" rather than special-casing bounds everywhere.
    def pixel_to_cell(self, x: int, y: int) -> Optional[Position]:
        board_x = x - self.board_offset_x

        if board_x < 0 or y < 0:
            return None

        row = y // self.cell_size
        col = board_x // self.cell_size

        if row < 0 or row >= self.height or col < 0 or col >= self.width:
            return None

        return Position(row, col)
