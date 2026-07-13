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


# Splits the .kfc protocol into its two raw sections: a "Board" header
# line, the board rows that follow it up to the first blank line, and
# every non-blank line after that as commands - no "Commands:" marker,
# matching every real script under tests/integration/scripts/*.kfc.
# Parsing each section's contents happens elsewhere (board_parser for the
# board lines, parse_line above for each command line).
def split_sections(text: str) -> Tuple[List[str], List[str]]:
    lines = text.splitlines()

    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1

    if i >= len(lines) or lines[i].strip().rstrip(":") != "Board":
        return [], []
    i += 1

    board_lines = []
    while i < len(lines) and lines[i].strip() != "":
        board_lines.append(lines[i].strip())
        i += 1

    command_lines = [line.strip() for line in lines[i:] if line.strip() != ""]
    return board_lines, command_lines
