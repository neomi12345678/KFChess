from model.board import Board
from model.piece import Piece
from model.position import Position

EMPTY_TOKEN = "."
VALID_COLORS = {"w", "b"}
VALID_KINDS = {"K", "Q", "R", "B", "N", "P"}


class BoardParseError(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def parse(text: str) -> Board:
    rows = [line.split() for line in text.splitlines() if line.strip() != ""]

    if not rows:
        return Board(width=0, height=0)

    width = len(rows[0])
    for r, row in enumerate(rows):
        if len(row) != width:
            raise BoardParseError(
                f"inconsistent row length: row {r} has {len(row)} cells, expected {width}",
                code="ROW_WIDTH_MISMATCH",
            )

    board = Board(width=width, height=len(rows))

    for r, row in enumerate(rows):
        for c, token in enumerate(row):
            if token == EMPTY_TOKEN:
                continue
            board.add_piece(Position(r, c), _parse_piece(token, r, c))

    return board


def _parse_piece(token: str, r: int, c: int) -> Piece:
    if len(token) != 2 or token[0] not in VALID_COLORS or token[1] not in VALID_KINDS:
        raise BoardParseError(f"illegal piece token '{token}' at row {r}, col {c}", code="UNKNOWN_TOKEN")

    color, kind = token[0], token[1]
    return Piece(id=f"{color}{kind}-{r}-{c}", color=color, kind=kind, cell=Position(r, c))
