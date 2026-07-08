from config import (
    BISHOP_KIND,
    BLACK_COLOR,
    KING_KIND,
    KNIGHT_KIND,
    PAWN_KIND,
    QUEEN_KIND,
    ROOK_KIND,
    WHITE_COLOR,
)

EMPTY = "."

PIECE_TYPES = {KING_KIND, QUEEN_KIND, ROOK_KIND, BISHOP_KIND, KNIGHT_KIND, PAWN_KIND}
PIECE_COLORS = {WHITE_COLOR, BLACK_COLOR}


def make(piece_color, piece_kind):
    return f"{piece_color}{piece_kind}"


def all_piece_names():
    return {make(c, t) for c in PIECE_COLORS for t in PIECE_TYPES}


def color(piece):
    return piece[0]


def kind(piece):
    return piece[1]


def other_color(c):
    return BLACK_COLOR if c == WHITE_COLOR else WHITE_COLOR


def is_king(piece):
    return not is_empty(piece) and kind(piece) == KING_KIND


def is_empty(cell):
    return cell == EMPTY
