from boardio.board_parser import parse as parse_board
from engine.game_engine import GameEngine
from input.controller_builder import build_controller
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine


def make_engine(board_text):
    board = parse_board(board_text)
    return board, GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=RealTimeArbiter(board))


def test_build_controller_wires_a_controller_that_acts_against_the_given_engine():
    board, game_engine = make_engine("wK . .\n. . .\n. . .")

    controller, _board_mapper = build_controller(game_engine, width=board.width, height=board.height)

    controller.click(Position(0, 0))

    assert controller.selected == Position(0, 0)


def test_build_controller_threads_cell_size_and_board_offset_into_the_board_mapper():
    board, game_engine = make_engine("wK . .\n. . .\n. . .")

    _controller, board_mapper = build_controller(
        game_engine, width=board.width, height=board.height, board_offset_x=260, cell_size=50
    )

    assert board_mapper.cell_size == 50
    assert board_mapper.board_offset_x == 260
    assert board_mapper.pixel_to_cell(260 + 10, 10) == Position(0, 0)
    assert board_mapper.pixel_to_cell(10, 10) is None  # un-shifted pixel now misses
