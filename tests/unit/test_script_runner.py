from boardio.board_parser import parse as parse_board
from engine.game_engine import GameEngine
from input.board_mapper import BoardMapper
from input.controller import Controller
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine
from texttests.script_runner import run_commands


def make_context(board_text):
    board = parse_board(board_text)
    arbiter = RealTimeArbiter(board)
    game_engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=arbiter)
    mapper = BoardMapper(width=board.width, height=board.height)
    controller = Controller(game_engine=game_engine)
    return board, controller, game_engine, mapper


def test_run_commands_executes_click_and_wait_and_prints_the_result():
    board, controller, game_engine, mapper = make_context("wR . .")
    printed = []

    run_commands(
        ["click 50 50", "click 250 50", "wait 2000", "print board"],
        controller,
        game_engine,
        board,
        mapper,
        print_fn=printed.append,
    )

    assert printed == [". . wR"]


def test_run_commands_executes_a_jump_command():
    board, controller, game_engine, mapper = make_context(". wK .")
    printed = []

    run_commands(
        ["jump 150 50", "wait 1000", "print board"],
        controller,
        game_engine,
        board,
        mapper,
        print_fn=printed.append,
    )

    assert printed == [". wK ."]


def test_run_commands_ignores_blank_and_unrecognized_lines():
    board, controller, game_engine, mapper = make_context("wR . .")
    printed = []

    run_commands(
        ["", "not a real command", "click 50 50", "click 250 50", "wait 2000", "print board"],
        controller,
        game_engine,
        board,
        mapper,
        print_fn=printed.append,
    )

    assert printed == [". . wR"]
