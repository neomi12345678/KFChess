from typing import List

from board import BoardValidationError, parse_board, validate_board
from commands import parse_commands
from config import BOARD_MARKER, COMMANDS_MARKER
from handlers.print_board import handle_print_board
from handlers.registry import COMMAND_HANDLERS
from state import GameState


def run(lines: List[str], output=None):
    if output is None:
        from sys import stdout

        output = stdout

    if BOARD_MARKER not in lines:
        return None

    try:
        board = parse_board(lines)
        validate_board(board)
    except BoardValidationError as error:
        output.write(f"ERROR {error.code}\n")
        return None

    state = GameState(board=board)

    if COMMANDS_MARKER not in lines:
        # No commands section at all: this is the "pure parse/validate/print"
        # case (the original, pre-command iteration). There is no explicit
        # `print board` to wait for, so we print the canonical board once and
        # we're done. This branch must NOT run when a Commands: section is
        # present but simply lacks a `print board` line - that case stays
        # silent, exactly as before, to avoid changing behavior any later
        # iteration already depends on.
        handle_print_board(state, output)
        return state.board

    commands = parse_commands(lines)

    for command in commands:
        COMMAND_HANDLERS[type(command)](state, command, output)

    return state.board
