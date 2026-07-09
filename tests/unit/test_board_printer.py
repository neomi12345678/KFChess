from boardio.board_parser import parse
from boardio.board_printer import print_board


def test_print_board_round_trips_a_simple_board():
    text = "wK . .\n. wR .\n. . bK"

    board = parse(text)

    assert print_board(board) == text


def test_print_board_prints_dots_for_empty_cells():
    board = parse(". .\n. .")

    assert print_board(board) == ". .\n. ."
