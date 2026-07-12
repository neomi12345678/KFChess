from dataclasses import dataclass
from typing import List, Optional


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
