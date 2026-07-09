import pytest

from model.board import Board, DuplicatePieceIdError, OccupiedCellError
from model.piece import Piece
from model.position import Position


def make_piece(piece_id, color, kind, cell):
    return Piece(id=piece_id, color=color, kind=kind, cell=cell)


def test_board_stores_width_and_height():
    board = Board(width=8, height=8)

    assert board.width == 8
    assert board.height == 8


def test_is_in_bounds_accepts_cells_within_the_board():
    board = Board(width=3, height=2)

    assert board.is_in_bounds(Position(0, 0))
    assert board.is_in_bounds(Position(1, 2))


def test_is_in_bounds_rejects_cells_outside_the_board():
    board = Board(width=3, height=2)

    assert not board.is_in_bounds(Position(-1, 0))
    assert not board.is_in_bounds(Position(0, 3))
    assert not board.is_in_bounds(Position(2, 0))


def test_get_piece_returns_none_for_empty_cell():
    board = Board(width=3, height=3)

    assert board.get_piece(Position(0, 0)) is None


def test_add_piece_then_get_piece_returns_it():
    board = Board(width=3, height=3)
    piece = make_piece("w-r-1", "w", "R", Position(0, 0))

    board.add_piece(Position(0, 0), piece)

    assert board.get_piece(Position(0, 0)) == piece


def test_add_piece_sets_the_piece_cell():
    board = Board(width=3, height=3)
    piece = make_piece("w-r-1", "w", "R", cell=None)

    board.add_piece(Position(0, 0), piece)

    assert piece.cell == Position(0, 0)


def test_add_piece_rejects_duplicate_occupancy():
    board = Board(width=3, height=3)
    board.add_piece(Position(0, 0), make_piece("w-r-1", "w", "R", Position(0, 0)))

    with pytest.raises(OccupiedCellError):
        board.add_piece(Position(0, 0), make_piece("b-p-1", "b", "P", Position(0, 0)))


def test_add_piece_rejects_duplicate_piece_id():
    board = Board(width=3, height=3)
    board.add_piece(Position(0, 0), make_piece("w-r-1", "w", "R", Position(0, 0)))

    with pytest.raises(DuplicatePieceIdError):
        board.add_piece(Position(0, 1), make_piece("w-r-1", "w", "P", Position(0, 1)))


def test_remove_piece_clears_the_cell():
    board = Board(width=3, height=3)
    board.add_piece(Position(0, 0), make_piece("w-r-1", "w", "R", Position(0, 0)))

    board.remove_piece(Position(0, 0))

    assert board.get_piece(Position(0, 0)) is None


def test_remove_piece_frees_its_id_for_reuse():
    board = Board(width=3, height=3)
    board.add_piece(Position(0, 0), make_piece("w-r-1", "w", "R", Position(0, 0)))
    board.remove_piece(Position(0, 0))

    board.add_piece(Position(1, 1), make_piece("w-r-1", "w", "R", Position(1, 1)))

    assert board.get_piece(Position(1, 1)).id == "w-r-1"


def test_move_piece_relocates_it_to_the_destination():
    board = Board(width=3, height=3)
    piece = make_piece("w-r-1", "w", "R", Position(0, 0))
    board.add_piece(Position(0, 0), piece)

    board.move_piece(Position(0, 0), Position(0, 1))

    assert board.get_piece(Position(0, 0)) is None
    assert board.get_piece(Position(0, 1)) == piece


def test_move_piece_updates_the_piece_cell():
    board = Board(width=3, height=3)
    piece = make_piece("w-r-1", "w", "R", Position(0, 0))
    board.add_piece(Position(0, 0), piece)

    board.move_piece(Position(0, 0), Position(0, 1))

    assert piece.cell == Position(0, 1)


def test_move_piece_rejects_duplicate_occupancy_at_destination():
    board = Board(width=3, height=3)
    board.add_piece(Position(0, 0), make_piece("w-r-1", "w", "R", Position(0, 0)))
    board.add_piece(Position(0, 1), make_piece("b-p-1", "b", "P", Position(0, 1)))

    with pytest.raises(OccupiedCellError):
        board.move_piece(Position(0, 0), Position(0, 1))
