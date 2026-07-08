import pytest

from board import BoardValidationError, parse_board, validate_board
from piece import EMPTY


def test_parse_board():
    lines = [
        'Board:',
        'wK .',
        '. bK',
        'Commands:'
    ]

    board = parse_board(lines)
    assert board == [['wK', '.'], ['.', 'bK']]


def test_parse_board_empty_lines():
    lines = [
        'Board:',
        'wK .',
        '',
        '. bK',
        'Commands:'
    ]

    board = parse_board(lines)
    assert board == [['wK', '.'], ['.', 'bK']]


def test_parse_board_no_commands():
    lines = [
        'Board:',
        'wK .',
        '. bK',
    ]

    board = parse_board(lines)
    assert board == [['wK', '.'], ['.', 'bK']]


def test_validate_board_accepts_legal_board():
    board = [['wK', 'bQ'], ['.', 'wP']]
    validate_board(board)


def test_validate_board_accepts_all_piece_types():
    board = [['wK', 'wQ', 'wR', 'wB', 'wN', 'wP'],
             ['bK', 'bQ', 'bR', 'bB', 'bN', 'bP']]
    validate_board(board)


def test_validate_board_accepts_empty_board():
    board = []
    validate_board(board)


def test_validate_board_rejects_row_width_mismatch():
    board = [['wK', 'bQ'], ['wP']]
    with pytest.raises(BoardValidationError) as exc_info:
        validate_board(board)
    assert exc_info.value.code == 'ROW_WIDTH_MISMATCH'


def test_validate_board_rejects_unknown_token():
    board = [['wK', 'xY']]
    with pytest.raises(BoardValidationError) as exc_info:
        validate_board(board)
    assert exc_info.value.code == 'UNKNOWN_TOKEN'
