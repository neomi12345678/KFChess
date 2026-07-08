from dataclasses import dataclass
from typing import List, Union

from config import (
    CMD_CLICK,
    CMD_JUMP,
    CMD_PRINT,
    CMD_PRINT_BOARD_ARG,
    CMD_WAIT,
    COMMANDS_MARKER,
)


@dataclass
class ClickCommand:
    x: int
    y: int


@dataclass
class WaitCommand:
    ms: int


@dataclass
class JumpCommand:
    x: int
    y: int


@dataclass
class PrintBoardCommand:
    pass


Command = Union[ClickCommand, JumpCommand, WaitCommand, PrintBoardCommand]


def parse_commands(lines: List[str]) -> List[Command]:
    if COMMANDS_MARKER not in lines:
        return []

    i = lines.index(COMMANDS_MARKER) + 1
    commands: List[Command] = []

    while i < len(lines):
        raw = lines[i].strip()
        if not raw:
            i += 1
            continue

        parts = raw.split()
        if parts[0] == CMD_CLICK and len(parts) == 3:
            commands.append(ClickCommand(int(parts[1]), int(parts[2])))
        elif parts[0] == CMD_JUMP and len(parts) == 3:
            commands.append(JumpCommand(int(parts[1]), int(parts[2])))
        elif parts[0] == CMD_WAIT and len(parts) == 2:
            commands.append(WaitCommand(int(parts[1])))
        elif parts[0] == CMD_PRINT and len(parts) > 1 and parts[1] == CMD_PRINT_BOARD_ARG:
            commands.append(PrintBoardCommand())

        i += 1

    return commands
