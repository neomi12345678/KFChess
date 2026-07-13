from model.board import Board
from model.piece import Piece, ROOK, WHITE
from model.position import Position
from realtime.route_planner import retreat_cell


def test_retreat_cell_returns_source_for_a_non_straight_line():
    board = Board(width=3, height=3)

    result = retreat_cell(board, source=Position(2, 0), destination=Position(0, 1))

    assert result == Position(2, 0)


def test_retreat_cell_returns_the_cell_just_short_of_destination_when_it_is_open():
    board = Board(width=4, height=1)

    result = retreat_cell(board, source=Position(0, 0), destination=Position(0, 3))

    assert result == Position(0, 2)


def test_retreat_cell_walks_back_past_a_second_occupied_cell_to_find_an_open_one():
    board = Board(width=4, height=1)
    blocker = Piece(id="wR-0-2", color=WHITE, kind=ROOK, cell=Position(0, 2))
    board.add_piece(Position(0, 2), blocker)

    # (0, 2) is occupied, so the walk-back has to continue past it to (0, 1).
    result = retreat_cell(board, source=Position(0, 0), destination=Position(0, 3))

    assert result == Position(0, 1)


def test_retreat_cell_falls_back_all_the_way_to_source_when_the_whole_path_is_blocked():
    board = Board(width=4, height=1)
    board.add_piece(Position(0, 1), Piece(id="wR-0-1", color=WHITE, kind=ROOK, cell=Position(0, 1)))
    board.add_piece(Position(0, 2), Piece(id="wR-0-2", color=WHITE, kind=ROOK, cell=Position(0, 2)))

    result = retreat_cell(board, source=Position(0, 0), destination=Position(0, 3))

    assert result == Position(0, 0)
