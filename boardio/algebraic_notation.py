"""Turns a move/jump into display text for the moves-log side panel
(view/observers.py's MoveLogObserver) - purely cosmetic, never read back by
any game logic.

Deliberately simplified compared to standard chess SAN: no check/checkmate
suffix (this variant has no "check" concept - the game ends on a direct
king capture, see rules.rule_engine.KingCaptureWinCondition), no castling
notation (this variant's rules never produce a castling move), and no
disambiguation between two same-kind pieces that could reach the same
square (an accepted display-only simplification, not a full SAN replacement).
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
