from config import EMPTY_TOKEN
from model.board import Board
from model.piece import COLOR_BY_LETTER, KIND_BY_LETTER, Piece, PieceRepresentation
from model.position import Position

_LETTER_BY_COLOR = {color: letter for letter, color in COLOR_BY_LETTER.items()}
_LETTER_BY_KIND = {kind: letter for letter, kind in KIND_BY_LETTER.items()}

VALID_COLORS = set(COLOR_BY_LETTER)
VALID_KINDS = set(KIND_BY_LETTER)


class BoardParseError(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def parse(text: str) -> Board:
    rows = [line.split() for line in text.splitlines() if line.strip() != ""]

    if not rows:
        return Board(width=0, height=0)

    # All rows must share the first row's width before any piece is placed,
    # so a malformed board never gets partially built.
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

    # Translate notation letters to the domain's semantic values here -
    # this is the only place that needs to know both vocabularies.
    color_letter, kind_letter = token[0], token[1]
    return Piece(
        id=f"{token}-{r}-{c}",
        color=COLOR_BY_LETTER[color_letter],
        kind=KIND_BY_LETTER[kind_letter],
        cell=Position(r, c),
    )


# The inverse of _parse_piece: a semantic piece back to a two-letter token.
def piece_to_token(piece: PieceRepresentation) -> str:
    return f"{_LETTER_BY_COLOR[piece.color]}{_LETTER_BY_KIND[piece.kind]}"
