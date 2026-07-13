from dataclasses import dataclass
from typing import List, Optional

from model.board import Board
from model.piece import Piece
from model.position import Position


@dataclass
class GameState:
    board: Board


# Shared event/snapshot vocabulary: the engine, the real-time arbiter, and
# the view all need these shapes, so they live here instead of being
# duplicated or owned by whichever module happens to produce them first.


@dataclass
class MoveResult:
    is_accepted: bool
    reason: str


@dataclass
class JumpResult:
    is_accepted: bool
    reason: str


@dataclass
class ArrivalEvent:
    piece: Piece
    captured_piece: Optional[Piece]


@dataclass
class PieceSnapshot:
    id: str
    kind: str
    color: str
    pixel_x: int
    pixel_y: int
    state: str


@dataclass
class GameSnapshot:
    board_width: int
    board_height: int
    pieces: List[PieceSnapshot]
    selected_cell: Optional[Position]
    game_over: bool
