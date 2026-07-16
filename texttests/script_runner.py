from typing import Callable, List

from boardio.board_printer import print_board
from model.board import Board
from texttests.script_parser import parse_line


# Shared by main.py (the real CLI) and the .kfc integration tests - the
# only place that knows what each command word actually does. click/jump
# commands carry raw pixel coordinates (matching a real mouse click), so
# board_mapper resolves them to a cell before Controller ever sees them -
# see input/controller.py for why Controller itself never touches a pixel.
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

        if command.name == "click":
            cell = board_mapper.pixel_to_cell(int(command.args[0]), int(command.args[1]))
            controller.click(cell)
        elif command.name == "jump":
            cell = board_mapper.pixel_to_cell(int(command.args[0]), int(command.args[1]))
            controller.jump(cell)
        elif command.name == "wait":
            game_engine.wait(int(command.args[0]))
        elif command.name == "print" and command.args[:1] == ["board"]:
            print_fn(print_board(board))
