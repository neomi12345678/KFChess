from typing import Dict, Optional, Protocol, Set

from model.piece import Piece
from model.position import Position


class OccupiedCellError(Exception):
    def __init__(self, position: Position):
        super().__init__(f"cell already occupied: {position}")
        self.position = position


class DuplicatePieceIdError(Exception):
    def __init__(self, piece_id: str):
        super().__init__(f"duplicate piece id: {piece_id}")
        self.piece_id = piece_id


class BoardRepresentation(Protocol):
    """The storage contract every board implementation must satisfy.

    Rules, the engine, and the arbiter depend only on this interface, never
    on a concrete storage format - so a future binary/bitboard
    representation can be dropped in, implementing just these members,
    without touching a single line of game logic.
    """

    width: int
    height: int

    def is_in_bounds(self, position: Position) -> bool: ...

    def get_piece(self, position: Position) -> Optional[Piece]: ...

    def add_piece(self, position: Position, piece: Piece) -> None: ...

    def remove_piece(self, position: Position) -> None: ...

    def move_piece(self, src: Position, dst: Position) -> None: ...


class Board:
    """The standard in-memory BoardRepresentation: cells kept in a dict."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._cells: Dict[Position, Piece] = {}
        self._piece_ids: Set[str] = set()

    def is_in_bounds(self, position: Position) -> bool:
        return 0 <= position.row < self.height and 0 <= position.col < self.width

    def get_piece(self, position: Position) -> Optional[Piece]:
        return self._cells.get(position)

    def add_piece(self, position: Position, piece: Piece) -> None:
        if position in self._cells:
            raise OccupiedCellError(position)
        if piece.id in self._piece_ids:
            raise DuplicatePieceIdError(piece.id)
        piece.cell = position
        self._cells[position] = piece
        self._piece_ids.add(piece.id)

    def remove_piece(self, position: Position) -> None:
        piece = self._cells.pop(position)
        self._piece_ids.discard(piece.id)

    def move_piece(self, src: Position, dst: Position) -> None:
        if dst in self._cells:
            raise OccupiedCellError(dst)
        piece = self._cells.pop(src)
        piece.cell = dst
        self._cells[dst] = piece
