from dataclasses import dataclass

from model.piece import Piece
from model.position import Position

CELL_DURATION_MS = 1000


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
