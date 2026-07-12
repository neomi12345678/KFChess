from boardio.board_parser import parse
from model.position import Position
from rules.board_rules import BoardRules


def test_check_accepts_a_move_within_bounds_onto_an_empty_cell():
    board = parse(". . .\n. wR .\n. . .")
    rules = BoardRules()

    result = rules.check(board, Position(1, 1), Position(0, 1))

    assert result.is_valid is True
    assert result.reason == "ok"


def test_check_rejects_outside_board_destination():
    board = parse(". . .\n. wR .\n. . .")
    rules = BoardRules()

    result = rules.check(board, Position(1, 1), Position(5, 5))

    assert result.is_valid is False
    assert result.reason == "outside_board"


def test_check_rejects_outside_board_source():
    board = parse(". . .\n. wR .\n. . .")
    rules = BoardRules()

    result = rules.check(board, Position(-1, -1), Position(1, 1))

    assert result.is_valid is False
    assert result.reason == "outside_board"


def test_check_rejects_empty_source():
    board = parse(". . .\n. . .\n. . .")
    rules = BoardRules()

    result = rules.check(board, Position(1, 1), Position(0, 1))

    assert result.is_valid is False
    assert result.reason == "empty_source"


def test_check_rejects_friendly_destination():
    board = parse(". wP .\n. wR .\n. . .")
    rules = BoardRules()

    result = rules.check(board, Position(1, 1), Position(0, 1))

    assert result.is_valid is False
    assert result.reason == "friendly_destination"


def test_check_accepts_an_enemy_occupied_destination():
    board = parse(". bP .\n. wR .\n. . .")
    rules = BoardRules()

    result = rules.check(board, Position(1, 1), Position(0, 1))

    assert result.is_valid is True
    assert result.reason == "ok"
