"""Central configuration for KFChess.

All timing, sizing, and notation constants live here so game logic never
hardcodes magic numbers - changing a duration or a token only requires
editing this file, no other module should contain literal values like
these.
"""

CELL_SIZE = 100
EMPTY_TOKEN = "."

# Real-world scale we chose for converting the animation assets'
# physics.speed_m_per_sec (assets/pieces/*/states/*/config.json) into a
# per-cell duration: a real ~5.7cm chess square at those speeds would cross
# in ~40ms - too fast to see - so we treat one square as one meter instead,
# which conveniently also means CELL_SIZE pixels == 1 meter.
#
# Every other piece of real-time timing (move-cell duration, jump hangtime,
# short_rest/long_rest length) is read per-piece from each piece's own
# assets/pieces/<code>/states/<state>/config.json instead of a global
# constant here - see piece_config.py and realtime/motion.py's
# move_cell_duration_ms/animation_cycle_duration_ms.
METERS_PER_SQUARE = 1.0

# Movement shapes, as (row, col) deltas - the piece rules read these
# instead of hardcoding direction/offset tuples of their own.
ROOK_DIRECTIONS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
BISHOP_DIRECTIONS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
QUEEN_DIRECTIONS = ROOK_DIRECTIONS + BISHOP_DIRECTIONS
KNIGHT_OFFSETS = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
KING_OFFSETS = QUEEN_DIRECTIONS
