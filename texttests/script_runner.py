from typing import Callable, List

from boardio.board_printer import print_board
from model.board import Board
from texttests.script_parser import parse_line


def run_commands(
    lines: List[str],
    controller,
    game_engine,
    board: Board,
    print_fn: Callable[[str], None] = print,
) -> None:
    for line in lines:
        command = parse_line(line)
        if command is None:
            continue

        if command.name == "click":
            controller.click(int(command.args[0]), int(command.args[1]))
        elif command.name == "jump":
            controller.jump(int(command.args[0]), int(command.args[1]))
        elif command.name == "wait":
            game_engine.wait(int(command.args[0]))
        elif command.name == "print" and command.args[:1] == ["board"]:
            print_fn(print_board(board))
