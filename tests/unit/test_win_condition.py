from boardio.board_parser import parse
from engine.game_engine import GameEngine
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine
from rules.win_condition import KingCaptureWinCondition


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
