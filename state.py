from dataclasses import dataclass
from typing import List, Optional, Tuple


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
