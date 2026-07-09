from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.io.board_parser import parse
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine


class FakeGameEngine:
    def __init__(self):
        self.requested_moves = []

    def request_move(self, source, destination):
        self.requested_moves.append((source, destination))


def make_controller(board_text):
    board = parse(board_text)
    mapper = BoardMapper(width=board.width, height=board.height)
    engine = FakeGameEngine()
    controller = Controller(board=board, board_mapper=mapper, game_engine=engine)
    return controller, engine


def test_first_click_on_a_piece_sets_selected_cell():
    controller, engine = make_controller("wK . .\n. . .\n. . .")

    result = controller.click(50, 50)

    assert controller.selected == Position(0, 0)
    assert result.selected == Position(0, 0)
    assert result.move_requested is False
    assert engine.requested_moves == []


def test_first_click_on_an_empty_cell_leaves_selection_empty():
    controller, engine = make_controller(". . .\n. . .\n. . .")

    controller.click(50, 50)

    assert controller.selected is None
    assert engine.requested_moves == []


def test_click_outside_the_board_with_no_selection_does_nothing():
    controller, engine = make_controller(". . .\n. . .\n. . .")

    controller.click(-10, 50)

    assert controller.selected is None
    assert engine.requested_moves == []


def test_click_outside_the_board_with_selection_cancels_it():
    controller, engine = make_controller("wK . .\n. . .\n. . .")
    controller.click(50, 50)

    controller.click(-10, 50)

    assert controller.selected is None
    assert engine.requested_moves == []


def test_second_in_board_click_sends_move_request_and_clears_selection():
    controller, engine = make_controller("wK . .\n. . .\n. . .")
    controller.click(50, 50)

    result = controller.click(250, 50)

    assert engine.requested_moves == [(Position(0, 0), Position(0, 2))]
    assert controller.selected is None
    assert result.move_requested is True


def test_selection_clears_after_second_click_even_when_the_engine_rejects_the_move():
    board = parse("wK wP .\n. . .\n. . .")
    mapper = BoardMapper(width=board.width, height=board.height)
    engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=RealTimeArbiter(board))
    controller = Controller(board=board, board_mapper=mapper, game_engine=engine)
    controller.click(50, 50)

    result = controller.click(150, 50)

    assert controller.selected is None
    assert result.move_requested is True
    assert board.get_piece(Position(0, 0)) is not None
    assert board.get_piece(Position(0, 1)) is not None
