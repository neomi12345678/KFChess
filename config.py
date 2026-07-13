"""Central configuration for KFChess.

All timing, sizing, and notation constants live here so game logic never
hardcodes magic numbers - changing a duration or a token only requires
editing this file, no other module should contain literal values like
these.
"""

CELL_SIZE = 100
EMPTY_TOKEN = "."

CELL_DURATION_MS = 1000
AIRBORNE_DURATION_MS = CELL_DURATION_MS

# How long a piece rests after finishing a motion or a jump before it can
# start another one.
COOLDOWN_DURATION_MS = CELL_DURATION_MS

# Movement shapes, as (row, col) deltas - the piece rules read these
# instead of hardcoding direction/offset tuples of their own.
ROOK_DIRECTIONS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
BISHOP_DIRECTIONS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
QUEEN_DIRECTIONS = ROOK_DIRECTIONS + BISHOP_DIRECTIONS
KNIGHT_OFFSETS = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
KING_OFFSETS = QUEEN_DIRECTIONS
