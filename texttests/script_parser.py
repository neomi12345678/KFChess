from dataclasses import dataclass
from typing import List, Union


@dataclass
class SetBoardInstruction:
    rows: List[str]


@dataclass
class ClickInstruction:
    x: int
    y: int


@dataclass
class WaitInstruction:
    ms: int


@dataclass
class AssertPrintBoardInstruction:
    expected_rows: List[str]


Instruction = Union[SetBoardInstruction, ClickInstruction, WaitInstruction, AssertPrintBoardInstruction]


def parse(text: str) -> List[Instruction]:
    lines = text.splitlines()
    instructions: List[Instruction] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        if line == "Board":
            i += 1
            rows, i = _read_block(lines, i)
            instructions.append(SetBoardInstruction(rows=rows))
        elif line.startswith("click "):
            _, x, y = line.split()
            instructions.append(ClickInstruction(x=int(x), y=int(y)))
            i += 1
        elif line.startswith("wait "):
            _, ms = line.split()
            instructions.append(WaitInstruction(ms=int(ms)))
            i += 1
        elif line == "print board":
            i += 1
            rows, i = _read_block(lines, i)
            instructions.append(AssertPrintBoardInstruction(expected_rows=rows))
        else:
            i += 1

    return instructions


def _read_block(lines: List[str], i: int):
    rows = []
    while i < len(lines) and lines[i].strip() != "":
        rows.append(lines[i].strip())
        i += 1
    return rows, i
