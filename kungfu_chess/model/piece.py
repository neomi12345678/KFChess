from dataclasses import dataclass

from kungfu_chess.model.position import Position

IDLE = "idle"
MOVING = "moving"
CAPTURED = "captured"


@dataclass
class Piece:
    id: str
    color: str
    kind: str
    cell: Position
    state: str = IDLE
