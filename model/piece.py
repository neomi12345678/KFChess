from dataclasses import dataclass

from model.position import Position

# Semantic values, not board-notation letters - keeps rules/engine/arbiter
# code free of the "w"/"K" text tokens used only for parsing and printing.
WHITE = "white"
BLACK = "black"

KING = "king"
QUEEN = "queen"
ROOK = "rook"
BISHOP = "bishop"
KNIGHT = "knight"
PAWN = "pawn"

# A piece's real-time lifecycle state, independent of its board position.
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


# Single source of truth for board notation: which one-letter token stands
# for which color/kind. Adding a piece kind here is the only registration
# a custom board notation needs - boardio derives its valid-token set from
# these tables instead of hardcoding its own list.
COLOR_BY_LETTER = {"w": WHITE, "b": BLACK}
KIND_BY_LETTER = {"K": KING, "Q": QUEEN, "R": ROOK, "B": BISHOP, "N": KNIGHT, "P": PAWN}
