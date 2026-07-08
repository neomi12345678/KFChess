from piece import color, kind, make
from config import PAWN_KIND, QUEEN_KIND, WHITE_COLOR

"""Arrival rules for pieces.

The current implementation assumes that pieces are stateless beyond their color
and kind. To support a future rule like "pawn changes direction instead of
promoting", the piece model would need additional state (for example,
`direction`), and this hook would be the right place to handle that.
"""


def pawn_promotion(piece, r, rows):
    assert kind(piece) == PAWN_KIND

    last_row = 0 if color(piece) == WHITE_COLOR else rows - 1
    if r == last_row:
        return make(color(piece), QUEEN_KIND)
    return piece


ARRIVAL_RULES = {
    PAWN_KIND: pawn_promotion,
}


def on_arrival(piece, r, rows):
    rule = ARRIVAL_RULES.get(kind(piece))
    return rule(piece, r, rows) if rule else piece
