import pytest

from board import parse_board
from pieces import can_move, on_arrival
from piece import EMPTY


def test_can_move_king():
    board = [['wK', '.'], ['.', '.']]
    assert can_move(board, 'wK', 0, 0, 1, 1, 2)
    assert not can_move(board, 'wK', 0, 0, 2, 2, 3)


def test_can_move_rook_clear_path():
    board = [['wR', '.', '.'], ['.', '.', '.'], ['.', '.', '.']]
    assert can_move(board, 'wR', 0, 0, 0, 2, 3)


def test_can_move_rook_blocked():
    board = [['wR', 'wP', '.'], ['.', '.', '.'], ['.', '.', '.']]
    assert not can_move(board, 'wR', 0, 0, 0, 2, 3)


def test_can_move_bishop():
    board = [['wB', '.', '.'], ['.', '.', '.'], ['.', '.', '.']]
    assert can_move(board, 'wB', 0, 0, 2, 2, 3)


def test_can_move_knight():
    board = [['wN', '.', '.'], ['.', '.', '.'], ['.', '.', '.']]
    assert can_move(board, 'wN', 0, 0, 2, 1, 3)


def test_can_move_pawn_forward_and_capture():
    board = [['.', 'bN'], ['wP', '.'], ['.', '.']]
    assert can_move(board, 'wP', 1, 0, 0, 0, 3)
    assert can_move(board, 'wP', 1, 0, 0, 1, 3)


def test_can_move_black_pawn_forward():
    board = [['.', 'bP'], ['.', '.'], ['.', '.']]
    assert can_move(board, 'bP', 0, 1, 1, 1, 3)


def test_pawn_promotion_on_arrival():
    assert on_arrival('wP', 0, 2) == 'wQ'
    assert on_arrival('bP', 1, 2) == 'bQ'
    assert on_arrival('wP', 1, 2) == 'wQ'
