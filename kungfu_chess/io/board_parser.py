from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position

EMPTY_TOKEN = "."
VALID_COLORS = {"w", "b"}
VALID_KINDS = {"K", "Q", "R", "B", "N", "P"}


class BoardParseError(Exception):
    pass


def parse(text: str) -> Board:
    rows = [line.split() for line in text.splitlines() if line.strip() != ""]

    if not rows:
        return Board(width=0, height=0)

    width = len(rows[0])
    for row in rows:
        if len(row) != width:
            raise BoardParseError("inconsistent row length")

    board = Board(width=width, height=len(rows))

    for r, row in enumerate(rows):
        for c, token in enumerate(row):
            if token == EMPTY_TOKEN:
                continue
            board.add_piece(Position(r, c), _parse_piece(token, r, c))

    return board


def _parse_piece(token: str, r: int, c: int) -> Piece:
    if len(token) != 2 or token[0] not in VALID_COLORS or token[1] not in VALID_KINDS:
        raise BoardParseError(f"illegal piece token: {token}")

    color, kind = token[0], token[1]
    return Piece(id=f"{color}{kind}-{r}-{c}", color=color, kind=kind, cell=Position(r, c))
