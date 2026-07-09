from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    row: int
    col: int
