from dataclasses import dataclass

from model.position import Position

IDLE = "idle"
MOVING = "moving"
CAPTURED = "captured"
AIRBORNE = "airborne"


@dataclass
class Piece:
    id: str
    color: str
    kind: str
    cell: Position
    state: str = IDLE
