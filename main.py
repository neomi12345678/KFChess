# Git repo: https://github.com/neomi12345678/KFChess
import sys
from typing import IO, Optional

from boardio.board_parser import BoardParseError, parse as parse_board
from engine.game_builder import build_game
from input.controller_builder import build_controller
from texttests.script_parser import split_sections
from texttests.script_runner import run_commands


def run(text: str) -> str:
    board_lines, command_lines = split_sections(text)

    # A malformed board short-circuits the whole run - no commands execute.
    try:
        board = parse_board("\n".join(board_lines))
    except BoardParseError as error:
        return f"ERROR {error.code}"

    game_engine = build_game(board)
    controller, board_mapper = build_controller(game_engine, width=board.width, height=board.height)

    # Same command dispatcher the .kfc integration tests use - one
    # implementation of click/jump/wait/print board, not two.
    outputs = []
    run_commands(command_lines, controller, game_engine, board, board_mapper, print_fn=outputs.append)

    return "\n".join(outputs)


# input_stream/output_stream are injectable so tests can drive this
# function without monkeypatching sys.stdin/sys.stdout.
def main(input_stream: Optional[IO[str]] = None, output_stream: Optional[IO[str]] = None) -> None:
    input_stream = input_stream if input_stream is not None else sys.stdin
    output_stream = output_stream if output_stream is not None else sys.stdout
    output_stream.write(run(input_stream.read()) + "\n")


if __name__ == "__main__":  # pragma: no cover
    main()
