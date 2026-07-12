import pytest

from boardio.board_parser import BoardParseError, parse
from model.piece import KING, ROOK, WHITE
from model.position import Position


def test_parse_accepts_a_rectangular_board():
    board = parse("wK . .\n. wR .\n. . bK")

    assert board.width == 3
    assert board.height == 3


def test_parse_places_pieces_at_the_correct_cells():
    board = parse("wK . .\n. wR .\n. . bK")

    king = board.get_piece(Position(0, 0))
    assert king.color == WHITE
    assert king.kind == KING

    rook = board.get_piece(Position(1, 1))
    assert rook.color == WHITE
    assert rook.kind == ROOK

    assert board.get_piece(Position(0, 1)) is None


def test_parse_rejects_inconsistent_row_length():
    with pytest.raises(BoardParseError):
        parse("wK . .\n. wR")


def test_parse_rejects_illegal_piece_token():
    with pytest.raises(BoardParseError):
        parse("wK . .\n. wZ .\n. . bK")


def test_row_width_mismatch_error_has_structured_code():
    with pytest.raises(BoardParseError) as excinfo:
        parse("wK . .\n. bK")

    assert excinfo.value.code == "ROW_WIDTH_MISMATCH"


def test_unknown_token_error_has_structured_code():
    with pytest.raises(BoardParseError) as excinfo:
        parse("wK xZ\n. .")

    assert excinfo.value.code == "UNKNOWN_TOKEN"


def test_parse_empty_text_returns_empty_board():
    board = parse("")

    assert board.width == 0
    assert board.height == 0
