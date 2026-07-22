from typing import Callable, List

from boardio.board_printer import print_board
from model.board import Board
from texttests.script_parser import parse_line


# Shared by main.py (the real CLI) and the .kfc integration tests - the
# only place that knows what each command word actually does. click/jump
# commands carry raw pixel coordinates (matching a real mouse click), so
# board_mapper resolves them to a cell before Controller ever sees them -
# see input/controller.py for why Controller itself never touches a pixel.
def _run_click(command, controller, game_engine, board, board_mapper, print_fn) -> None:
    cell = board_mapper.pixel_to_cell(int(command.args[0]), int(command.args[1]))
    controller.click(cell)


def _run_jump(command, controller, game_engine, board, board_mapper, print_fn) -> None:
    cell = board_mapper.pixel_to_cell(int(command.args[0]), int(command.args[1]))
    controller.jump(cell)


def _run_wait(command, controller, game_engine, board, board_mapper, print_fn) -> None:
    game_engine.wait(int(command.args[0]))


def _run_print(command, controller, game_engine, board, board_mapper, print_fn) -> None:
    if command.args[:1] == ["board"]:
        print_fn(print_board(board))


# Command word -> handler. Every handler takes the same
# (command, controller, game_engine, board, board_mapper, print_fn) shape so
# this stays a plain lookup instead of a chain of "is it this word" checks.
_COMMAND_HANDLERS = {
    "click": _run_click,
    "jump": _run_jump,
    "wait": _run_wait,
    "print": _run_print,
}


def run_commands(
    lines: List[str],
    controller,
    game_engine,
    board: Board,
    board_mapper,
    print_fn: Callable[[str], None] = print,
) -> None:
    for line in lines:
        command = parse_line(line)
        if command is None:
            continue

        handler = _COMMAND_HANDLERS.get(command.name)
        if handler is not None:
            handler(command, controller, game_engine, board, board_mapper, print_fn)
