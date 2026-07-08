from dataclasses import dataclass
from typing import List, Optional, Tuple

from config import CELL_SIZE


@dataclass
class MovingPiece:
    piece: str
    sr: int
    sc: int
    r: int
    c: int
    remaining: int


@dataclass
class AirbornePiece:
    piece: str
    r: int
    c: int
    remaining: int


@dataclass
class GameState:
    board: List[List[str]]
    selected: Optional[Tuple[int, int]] = None
    moving_pieces: List[MovingPiece] = None
    airborne_pieces: List[AirbornePiece] = None
    game_over: bool = False

    def __post_init__(self):
        if self.moving_pieces is None:
            self.moving_pieces = []
        if self.airborne_pieces is None:
            self.airborne_pieces = []

    def is_cell_in_flight(self, r: int, c: int) -> bool:
        return any(mp.sr == r and mp.sc == c for mp in self.moving_pieces) or any(
            ap.r == r and ap.c == c for ap in self.airborne_pieces
        )


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
