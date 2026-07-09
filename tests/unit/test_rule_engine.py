from boardio.board_parser import parse
from model.position import Position
from rules.rule_engine import RuleEngine


def test_validate_move_accepts_a_legal_rook_move():
    board = parse(". . .\n. wR .\n. . .")
    engine = RuleEngine()

    result = engine.validate_move(board, Position(1, 1), Position(0, 1))

    assert result.is_valid is True
    assert result.reason == "ok"


def test_validate_move_rejects_outside_board_destination():
    board = parse(". . .\n. wR .\n. . .")
    engine = RuleEngine()

    result = engine.validate_move(board, Position(1, 1), Position(5, 5))

    assert result.is_valid is False
    assert result.reason == "outside_board"


def test_validate_move_rejects_outside_board_source():
    board = parse(". . .\n. wR .\n. . .")
    engine = RuleEngine()

    result = engine.validate_move(board, Position(-1, -1), Position(1, 1))

    assert result.is_valid is False
    assert result.reason == "outside_board"


def test_validate_move_rejects_empty_source():
    board = parse(". . .\n. . .\n. . .")
    engine = RuleEngine()

    result = engine.validate_move(board, Position(1, 1), Position(0, 1))

    assert result.is_valid is False
    assert result.reason == "empty_source"


def test_validate_move_rejects_friendly_destination():
    board = parse(". wP .\n. wR .\n. . .")
    engine = RuleEngine()

    result = engine.validate_move(board, Position(1, 1), Position(0, 1))

    assert result.is_valid is False
    assert result.reason == "friendly_destination"


def test_validate_move_rejects_illegal_piece_move():
    board = parse(". . .\n. wR .\n. . .")
    engine = RuleEngine()

    result = engine.validate_move(board, Position(1, 1), Position(0, 0))

    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"
