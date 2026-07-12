from dataclasses import dataclass


# Board coordinate, not a pixel coordinate. Frozen so it can be used as a
# dict key (Board indexes pieces by Position).
@dataclass(frozen=True)
class Position:
    row: int
    col: int
