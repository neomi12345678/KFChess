from config import KING_KIND

EMPTY = "."

PIECE_TYPES = {'K', 'Q', 'R', 'B', 'N', 'P'}
PIECE_COLORS = {'w', 'b'}


def make(piece_color, piece_kind):
    return f"{piece_color}{piece_kind}"


def all_piece_names():
    return {make(c, t) for c in PIECE_COLORS for t in PIECE_TYPES}


def color(piece):
    return piece[0]


def kind(piece):
    return piece[1]


def other_color(c):
    return 'b' if c == 'w' else 'w'

from config import KING_KIND


def is_king(piece):
    return not is_empty(piece) and kind(piece) == KING_KIND


def is_empty(cell):
    return cell == EMPTY
