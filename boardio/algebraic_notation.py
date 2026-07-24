"""Turns a move/jump into display text for the moves-log side panel
(events/observers.py's MoveLogObserver) - move_notation/jump_notation are
purely cosmetic, never read back by any game logic.

Deliberately simplified compared to standard chess SAN: no check/checkmate
suffix (this variant has no "check" concept - the game ends on a direct
king capture, see rules.rule_engine.KingCaptureWinCondition), no castling
notation (this variant's rules never produce a castling move), and no
disambiguation between two same-kind pieces that could reach the same
square (an accepted display-only simplification, not a full SAN replacement).

parse_square is the one function here that IS read back: the inverse of
square_name, for client/client_cli.py's own typed algebraic input ("e2e4",
"jump e4") - the one remaining place a player types a square by hand rather
than clicking one, now that the network wire format itself carries a
Position directly (see protocol/game_messages.py's own docstring).
"""

from model.piece import KIND_BY_LETTER, PAWN
from model.position import Position

_LETTER_BY_KIND = {kind: letter for letter, kind in KIND_BY_LETTER.items()}


# Column 0 is the "a" file, matching board_parser's left-to-right token
# order. Row 0 is rank <board_height> (black's back rank in the standard
# starting position), since white's pawns advance toward row 0 - see
# rules.piece_rules.PawnRule's own row/direction math.
def square_name(position: Position, board_height: int) -> str:
    file_letter = chr(ord("a") + position.col)
    rank_number = board_height - position.row
    return f"{file_letter}{rank_number}"


def parse_square(square: str, board_height: int) -> Position:
    if len(square) < 2 or not square[0].isalpha() or not square[1:].isdigit():
        raise ValueError(f"malformed square: '{square}'")

    col = ord(square[0].lower()) - ord("a")
    rank_number = int(square[1:])
    row = board_height - rank_number

    if col < 0:
        raise ValueError(f"malformed square: '{square}'")

    return Position(row, col)


def move_notation(kind: str, source: Position, destination: Position, board_height: int, is_capture: bool) -> str:
    dest = square_name(destination, board_height)

    if kind == PAWN:
        # Pawn captures name the source file instead of a piece letter
        # (pawns have none) - e.g. "exd5", matching standard SAN.
        if is_capture:
            source_file = chr(ord("a") + source.col)
            return f"{source_file}x{dest}"
        return dest

    letter = _LETTER_BY_KIND[kind]
    return f"{letter}x{dest}" if is_capture else f"{letter}{dest}"


# Jump is unique to this variant - a piece jumps in place, with no
# destination (see realtime.real_time_arbiter.RealTimeArbiter.start_jump) -
# so its notation marks the piece's own square instead of reusing
# move_notation's source->destination shape, with a "^" suffix so it reads
# as visibly distinct from an ordinary move in the log.
def jump_notation(kind: str, position: Position, board_height: int) -> str:
    square = square_name(position, board_height)
    if kind == PAWN:
        return f"{square}^"
    return f"{_LETTER_BY_KIND[kind]}{square}^"
