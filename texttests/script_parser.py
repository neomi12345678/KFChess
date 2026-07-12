from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class Command:
    name: str
    args: List[str]


# Generic tokenizer only - it has no idea "click"/"wait"/"jump" exist.
# Adding a new command never requires touching this file, only the
# dispatcher that interprets Command.name.
def parse_line(line: str) -> Optional[Command]:
    parts = line.strip().split()
    if not parts:
        return None
    return Command(name=parts[0], args=parts[1:])


# Splits the VPL-style "Board:" / "Commands:" protocol into its two raw
# sections; parsing each section's contents happens elsewhere (board_parser
# for the board lines, parse_line above for each command line).
def split_sections(text: str) -> Tuple[List[str], List[str]]:
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
