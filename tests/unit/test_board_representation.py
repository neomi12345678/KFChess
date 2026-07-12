from typing import Optional

from model.piece import Piece, ROOK, WHITE
from model.position import Position
from rules.rule_engine import RuleEngine


class FlatListBoard:
    """A second BoardRepresentation with a completely different storage
    layout (a flat list instead of a dict keyed by Position), to prove
    that game logic really does depend on the interface and not on
    Board's specific internals."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._cells = [None] * (width * height)

    def _index(self, position: Position) -> int:
        return position.row * self.width + position.col

    def is_in_bounds(self, position: Position) -> bool:
        return 0 <= position.row < self.height and 0 <= position.col < self.width

    def get_piece(self, position: Position) -> Optional[Piece]:
        return self._cells[self._index(position)]

    def add_piece(self, position: Position, piece: Piece) -> None:
        piece.cell = position
        self._cells[self._index(position)] = piece

    def remove_piece(self, position: Position) -> None:
        self._cells[self._index(position)] = None

    def move_piece(self, src: Position, dst: Position) -> None:
        piece = self._cells[self._index(src)]
        self._cells[self._index(src)] = None
        piece.cell = dst
        self._cells[self._index(dst)] = piece


def test_rule_engine_validates_moves_against_a_non_dict_board_representation():
    board = FlatListBoard(width=3, height=3)
    rook = Piece(id="wR-1-1", color=WHITE, kind=ROOK, cell=Position(1, 1))
    board.add_piece(Position(1, 1), rook)

    result = RuleEngine().validate_move(board, Position(1, 1), Position(1, 2))

    assert result.is_valid is True
    assert result.reason == "ok"


def test_flat_list_board_remove_and_move_piece():
    board = FlatListBoard(width=3, height=3)
    rook = Piece(id="wR-0-0", color=WHITE, kind=ROOK, cell=Position(0, 0))
    board.add_piece(Position(0, 0), rook)

    board.move_piece(Position(0, 0), Position(0, 1))

    assert board.get_piece(Position(0, 0)) is None
    assert board.get_piece(Position(0, 1)) is rook
    assert rook.cell == Position(0, 1)

    board.remove_piece(Position(0, 1))

    assert board.get_piece(Position(0, 1)) is None
