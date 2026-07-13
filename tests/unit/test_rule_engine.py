import pytest

from boardio.board_parser import parse
from engine.game_engine import GameEngine
from model.piece import KING, PAWN, QUEEN, ROOK
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.piece_rules import KingRule
from rules.rule_engine import (
    IncompletePieceRuleRegistryError,
    KingCaptureWinCondition,
    LastRankPromotion,
    RuleEngine,
    ensure_covers,
)


def test_ensure_covers_raises_when_a_piece_kind_has_no_registered_rule():
    with pytest.raises(IncompletePieceRuleRegistryError) as excinfo:
        ensure_covers({KING: KingRule()}, {KING, PAWN})

    assert excinfo.value.missing_kinds == [PAWN]


def test_ensure_covers_accepts_a_registry_with_every_kind_present():
    ensure_covers({KING: KingRule()}, {KING})


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


def test_king_capture_win_condition_true_when_a_king_is_captured():
    piece = parse("wK . .").get_piece(Position(0, 0))

    assert KingCaptureWinCondition().is_game_over(piece) is True


def test_king_capture_win_condition_false_for_a_non_king_capture():
    piece = parse("wP . .").get_piece(Position(0, 0))

    assert KingCaptureWinCondition().is_game_over(piece) is False


def test_king_capture_win_condition_false_when_nothing_was_captured():
    assert KingCaptureWinCondition().is_game_over(None) is False


class NeverEndsWinCondition:
    def is_game_over(self, captured_piece):
        return False


def test_game_engine_accepts_a_custom_win_condition():
    board = parse("wR . bK")
    engine = GameEngine(
        board=board,
        rule_engine=RuleEngine(),
        real_time_arbiter=RealTimeArbiter(board),
        win_condition=NeverEndsWinCondition(),
    )

    engine.request_move(Position(0, 0), Position(0, 2))
    engine.wait(2000)

    assert engine.game_over is False


def test_last_rank_promotion_promotes_a_white_pawn_at_row_zero():
    board = parse(". . .\n. wP .")
    pawn = board.get_piece(Position(1, 1))
    pawn.cell = Position(0, 1)

    LastRankPromotion().promote(pawn, board.height)

    assert pawn.kind == QUEEN


def test_last_rank_promotion_leaves_a_pawn_alone_before_the_last_rank():
    board = parse(". . .\n. wP .\n. . .")
    pawn = board.get_piece(Position(1, 1))

    LastRankPromotion().promote(pawn, board.height)

    assert pawn.kind == PAWN


def test_last_rank_promotion_ignores_non_pawns():
    board = parse("wR . .")
    rook = board.get_piece(Position(0, 0))

    LastRankPromotion().promote(rook, board.height)

    assert rook.kind == ROOK


def test_last_rank_promotion_promotion_target_is_configurable():
    board = parse(". . .\n. wP .")
    pawn = board.get_piece(Position(1, 1))
    pawn.cell = Position(0, 1)

    LastRankPromotion(promote_to=ROOK).promote(pawn, board.height)

    assert pawn.kind == ROOK


class NoPromotion:
    def promote(self, piece, board_height):
        pass


def test_real_time_arbiter_accepts_a_custom_promotion_rule():
    board = parse(". . .\n. wP .")
    arbiter = RealTimeArbiter(board, promotion_rule=NoPromotion())
    pawn = board.get_piece(Position(1, 1))

    arbiter.start_motion(pawn, Position(1, 1), Position(0, 1))
    arbiter.advance_time(1000)

    assert board.get_piece(Position(0, 1)).kind == PAWN
