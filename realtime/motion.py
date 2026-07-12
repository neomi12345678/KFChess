from dataclasses import dataclass
from typing import List

from config import AIRBORNE_DURATION_MS, CELL_DURATION_MS
from model.piece import Piece
from model.position import Position


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


# The cells a motion actually crosses, used to detect route conflicts
# between two concurrently moving pieces. Orthogonal/diagonal moves are
# walked cell-by-cell; anything else (a knight's L-shape) is treated as a
# jump - only its source and destination count, matching how knights
# already ignore what's in between.
def compute_path(source: Position, destination: Position) -> List[Position]:
    row_diff = destination.row - source.row
    col_diff = destination.col - source.col

    is_straight_line = row_diff == 0 or col_diff == 0 or abs(row_diff) == abs(col_diff)
    if not is_straight_line:
        return [source, destination]

    row_step = _sign(row_diff)
    col_step = _sign(col_diff)
    steps = max(abs(row_diff), abs(col_diff))

    return [Position(source.row + row_step * i, source.col + col_step * i) for i in range(steps + 1)]


# A piece currently traveling from source to destination.
@dataclass
class Motion:
    piece: Piece
    source: Position
    destination: Position
    elapsed_ms: int = 0

    @property
    def duration_ms(self) -> int:
        cells = max(
            abs(self.destination.row - self.source.row),
            abs(self.destination.col - self.source.col),
        )
        return cells * CELL_DURATION_MS

    def is_complete(self) -> bool:
        return self.elapsed_ms >= self.duration_ms

    def path(self) -> List[Position]:
        return compute_path(self.source, self.destination)


# A piece that jumped and is temporarily immune where it stands - it
# doesn't move, it just holds its cell for a limited window.
@dataclass
class Airborne:
    piece: Piece
    elapsed_ms: int = 0

    def is_expired(self) -> bool:
        return self.elapsed_ms >= AIRBORNE_DURATION_MS
