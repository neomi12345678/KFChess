import pytest

from kungfu_chess.io.board_parser import BoardParseError, parse
from kungfu_chess.model.position import Position


def test_parse_accepts_a_rectangular_board():
    board = parse("wK . .\n. wR .\n. . bK")

    assert board.width == 3
    assert board.height == 3


def test_parse_places_pieces_at_the_correct_cells():
    board = parse("wK . .\n. wR .\n. . bK")

    king = board.get_piece(Position(0, 0))
    assert king.color == "w"
    assert king.kind == "K"

    rook = board.get_piece(Position(1, 1))
    assert rook.color == "w"
    assert rook.kind == "R"

    assert board.get_piece(Position(0, 1)) is None


def test_parse_rejects_inconsistent_row_length():
    with pytest.raises(BoardParseError):
        parse("wK . .\n. wR")


def test_parse_rejects_illegal_piece_token():
    with pytest.raises(BoardParseError):
        parse("wK . .\n. wZ .\n. . bK")


def test_parse_empty_text_returns_empty_board():
    board = parse("")

    assert board.width == 0
    assert board.height == 0
