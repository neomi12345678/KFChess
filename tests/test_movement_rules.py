import pytest

from rules.movement_rules import can_move, clear_path
from piece import EMPTY


def test_can_move_king():
    board = [['wK', '.', '.'], ['.', '.', '.'], ['.', '.', '.']]
    assert can_move(board, 'wK', 0, 0, 1, 1, 3)
    assert not can_move(board, 'wK', 0, 0, 2, 2, 3)


def test_can_move_king_one_step():
    board = [['wK', '.'], ['.', '.']]
    assert can_move(board, 'wK', 0, 0, 0, 1, 2)
    assert can_move(board, 'wK', 0, 0, 1, 0, 2)


def test_can_move_queen():
    board = [['wQ', '.', '.'], ['.', '.', '.'], ['.', '.', '.']]
    assert can_move(board, 'wQ', 0, 0, 0, 2, 3)
    assert can_move(board, 'wQ', 0, 0, 2, 2, 3)


def test_can_move_rook_clear_path():
    board = [['wR', '.', '.'], ['.', '.', '.'], ['.', '.', '.']]
    assert can_move(board, 'wR', 0, 0, 0, 2, 3)


def test_can_move_rook_blocked():
    board = [['wR', 'wP', '.'], ['.', '.', '.'], ['.', '.', '.']]
    assert not can_move(board, 'wR', 0, 0, 0, 2, 3)


def test_can_move_rook_blocked_by_friendly():
    board = [['wR', '.', 'wP'], ['.', '.', '.'], ['.', '.', '.']]
    assert not can_move(board, 'wR', 0, 0, 0, 2, 3)


def test_can_move_rook_vertical():
    board = [['wR', '.'], ['.', '.'], ['.', '.']]
    assert can_move(board, 'wR', 0, 0, 2, 0, 3)


def test_can_move_bishop():
    board = [['wB', '.', '.'], ['.', '.', '.'], ['.', '.', '.']]
    assert can_move(board, 'wB', 0, 0, 2, 2, 3)


def test_can_move_bishop_blocked():
    board = [['wB', '.', '.'], ['.', 'wP', '.'], ['.', '.', '.']]
    assert not can_move(board, 'wB', 0, 0, 2, 2, 3)


def test_can_move_knight():
    board = [['wN', '.', '.'], ['.', '.', '.'], ['.', '.', '.']]
    assert can_move(board, 'wN', 0, 0, 2, 1, 3)


def test_can_move_knight_jumps_blocker():
    board = [['wN', 'wP', 'wP'], ['.', '.', '.'], ['.', '.', '.']]
    assert can_move(board, 'wN', 0, 0, 2, 1, 3)


def test_can_move_knight_all_shapes():
    board = [['.', '.', '.', '.'], ['.', 'wN', '.', '.'], ['.', '.', '.', '.'], ['.', '.', '.', '.']]
    assert can_move(board, 'wN', 1, 1, 3, 2, 4)
    assert can_move(board, 'wN', 1, 1, 3, 0, 4)
    assert can_move(board, 'wN', 1, 1, 2, 3, 4)
    assert can_move(board, 'wN', 1, 1, 0, 3, 4)


def test_can_move_empty_piece():
    board = [[EMPTY, '.'], ['.', '.']]
    assert not can_move(board, EMPTY, 0, 0, 1, 1, 2)


def test_can_move_unknown_piece_type():
    board = [['xY', '.'], ['.', '.']]
    assert not can_move(board, 'xY', 0, 0, 1, 1, 2)


def test_can_move_pawn_forward_and_capture():
    board = [['.', 'bN'], ['wP', '.'], ['.', '.']]
    assert can_move(board, 'wP', 1, 0, 0, 0, 3)
    assert can_move(board, 'wP', 1, 0, 0, 1, 3)


def test_can_move_white_pawn_forward():
    board = [['.'], ['wP']]
    assert can_move(board, 'wP', 1, 0, 0, 0, 2)


def test_can_move_black_pawn_forward():
    board = [['.', 'bP'], ['.', '.'], ['.', '.']]
    assert can_move(board, 'bP', 0, 1, 1, 1, 3)


def test_can_move_white_pawn_two_step_from_start():
    board = [['.', '.', '.'] for _ in range(7)] + [['wP', '.', '.']]
    assert can_move(board, 'wP', 7, 0, 5, 0, 8)


def test_can_move_white_pawn_two_step_blocked():
    board = [['.', '.', '.'] for _ in range(6)] + [['bP', '.', '.'], ['wP', '.', '.']]
    assert not can_move(board, 'wP', 7, 0, 5, 0, 8)


def test_can_move_black_pawn_two_step_from_start():
    board = [['bP', '.', '.']] + [['.', '.', '.'] for _ in range(3)]
    assert can_move(board, 'bP', 0, 0, 2, 0, 4)


def test_can_move_white_pawn_double_from_middle_invalid():
    board = [['.', '.', '.'], ['.', '.', '.'], ['wP', '.', '.'], ['.', '.', '.']]
    assert not can_move(board, 'wP', 2, 0, 0, 0, 4)


def test_can_move_black_pawn_diagonal_capture():
    board = [['.', '.', '.'], ['bP', '.', '.'], ['.', 'wP', '.']]
    assert can_move(board, 'bP', 1, 0, 2, 1, 3)


def test_can_move_pawn_cannot_capture_forward():
    board = [['bP'], ['wP']]
    assert not can_move(board, 'wP', 1, 0, 0, 0, 2)


def test_can_move_pawn_cannot_move_two_from_wrong_row():
    board = [['.', '.', '.'], ['.', '.', '.'], ['.', '.', '.'], ['wP', '.', '.'], ['.', '.', '.'], ['.', '.', '.']]
    assert not can_move(board, 'wP', 3, 0, 1, 0, 6)


def test_clear_path_horizontal():
    board = [['wR', '.', '.', 'bK']]
    assert clear_path(board, 0, 0, 0, 3)


def test_clear_path_vertical():
    board = [['wR'], ['.'], ['.'], ['bK']]
    assert clear_path(board, 0, 0, 3, 0)


def test_clear_path_diagonal():
    board = [['wB', '.', '.'], ['.', '.', '.'], ['.', '.', 'bK']]
    assert clear_path(board, 0, 0, 2, 2)


def test_clear_path_blocked():
    board = [['wR', '.', 'wP', 'bK']]
    assert not clear_path(board, 0, 0, 0, 3)


def test_clear_path_adjacent():
    board = [['wR', 'bK']]
    assert clear_path(board, 0, 0, 0, 1)
