"""Piece codec layer.

This is the single extension point that must change when the internal piece
representation changes from text to binary. The rest of the game code works
through the piece API and does not depend on the text format.
"""

from piece import EMPTY, is_empty

Piece = str


def parse_piece_token(token: str) -> Piece:
    if token == EMPTY:
        return EMPTY
    return token


def format_piece(piece: Piece) -> str:
    return EMPTY if is_empty(piece) else piece
