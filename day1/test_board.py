import pytest

from board import parse_board, validate_board
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


def test_validate_board_accepts_legal_board():
    board = [['wK', 'bQ'], ['.', 'wP']]
    validate_board(board)


def test_validate_board_rejects_row_width_mismatch(capsys):
    board = [['wK', 'bQ'], ['wP']]
    with pytest.raises(SystemExit):
        validate_board(board)


def test_validate_board_rejects_unknown_token(capsys):
    board = [['wK', 'xY']]
    with pytest.raises(SystemExit):
        validate_board(board)
