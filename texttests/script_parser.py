from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Command:
    name: str
    args: List[str]


def parse_line(line: str) -> Optional[Command]:
    parts = line.strip().split()
    if not parts:
        return None
    return Command(name=parts[0], args=parts[1:])
