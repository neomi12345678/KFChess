from typing import List, Optional, Tuple

from config import CELL_SIZE


def pixel_to_cell(board: List[List[str]], x: int, y: int) -> Optional[Tuple[int, int]]:
    if x < 0 or y < 0:
        return None

    rows = len(board)
    cols = len(board[0]) if rows else 0
    r = y // CELL_SIZE
    c = x // CELL_SIZE

    if r < 0 or r >= rows or c < 0 or c >= cols:
        return None

    return r, c
