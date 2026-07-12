from dataclasses import dataclass

from model.position import Position

WHITE = "white"
BLACK = "black"

KING = "king"
QUEEN = "queen"
ROOK = "rook"
BISHOP = "bishop"
KNIGHT = "knight"
PAWN = "pawn"

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
