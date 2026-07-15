from pathlib import Path
from typing import List, Tuple

import pytest

from boardio.board_parser import parse as parse_board
from engine.game_engine import GameEngine
from input.board_mapper import BoardMapper
from input.controller import Controller
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine
from texttests.script_runner import run_commands

SCRIPTS_DIR = Path(__file__).parent / "scripts"


class ScriptAssertionError(Exception):
    pass


def _read_block(lines: List[str], i: int) -> Tuple[List[str], int]:
    rows = []
    while i < len(lines) and lines[i].strip() != "":
        rows.append(lines[i].strip())
        i += 1
    return rows, i


def _split_kfc_file(text: str):
    """A .kfc file is self-contained: a Board block, then commands, where each
    'print board' is immediately followed by the board it's expected to produce."""
    lines = text.splitlines()
    assert lines[0].strip() == "Board"

    board_lines, i = _read_block(lines, 1)

    command_lines: List[str] = []
    expected_blocks: List[List[str]] = []

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        command_lines.append(line)
        i += 1

        if line == "print board":
            block, i = _read_block(lines, i)
            expected_blocks.append(block)

    return board_lines, command_lines, expected_blocks


def run_kfc_script(text: str) -> None:
    board_lines, command_lines, expected_blocks = _split_kfc_file(text)
    board = parse_board("\n".join(board_lines))
    real_time_arbiter = RealTimeArbiter(board)
    game_engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=real_time_arbiter)
    board_mapper = BoardMapper(width=board.width, height=board.height)
    controller = Controller(board_mapper=board_mapper, game_engine=game_engine)

    printed: List[str] = []
    run_commands(command_lines, controller, game_engine, board, print_fn=printed.append)

    expected = ["\n".join(block) for block in expected_blocks]
    if printed != expected:
        raise ScriptAssertionError(f"print board mismatch:\nexpected:\n{expected}\nactual:\n{printed}")


@pytest.mark.parametrize("script_path", sorted(SCRIPTS_DIR.glob("*.kfc")), ids=lambda p: p.name)
def test_script(script_path):
    run_kfc_script(script_path.read_text())


def test_run_kfc_script_raises_when_the_printed_board_does_not_match():
    script = "Board\nwR . .\n\nprint board\n. wR .\n"

    with pytest.raises(ScriptAssertionError):
        run_kfc_script(script)
