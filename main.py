import sys

from boardio.board_parser import BoardParseError, parse as parse_board
from boardio.board_printer import print_board
from engine.game_engine import GameEngine
from input.board_mapper import BoardMapper
from input.controller import Controller
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine


def _split_sections(text: str):
    board_lines = []
    command_lines = []
    section = None

    for line in text.splitlines():
        stripped = line.strip()

        if stripped == "Board:":
            section = "board"
            continue
        if stripped == "Commands:":
            section = "commands"
            continue

        if section == "board":
            board_lines.append(stripped)
        elif section == "commands" and stripped:
            command_lines.append(stripped)

    return board_lines, command_lines


def run(text: str) -> str:
    board_lines, command_lines = _split_sections(text)

    try:
        board = parse_board("\n".join(board_lines))
    except BoardParseError as error:
        return f"ERROR {error.code}"

    real_time_arbiter = RealTimeArbiter(board)
    game_engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=real_time_arbiter)
    board_mapper = BoardMapper(width=board.width, height=board.height)
    controller = Controller(board=board, board_mapper=board_mapper, game_engine=game_engine)

    outputs = []
    for line in command_lines:
        parts = line.split()
        command = parts[0]

        if command == "click":
            controller.click(int(parts[1]), int(parts[2]))
        elif command == "jump":
            controller.jump(int(parts[1]), int(parts[2]))
        elif command == "wait":
            game_engine.wait(int(parts[1]))
        elif command == "print" and len(parts) > 1 and parts[1] == "board":
            outputs.append(print_board(board))

    return "\n".join(outputs)


def main() -> None:
    print(run(sys.stdin.read()))


if __name__ == "__main__":
    main()
