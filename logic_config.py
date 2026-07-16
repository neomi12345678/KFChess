"""Central configuration for game logic (rules/realtime/boardio).

All timing, duration, and movement-shape constants live here so game logic
never hardcodes magic numbers - changing a duration only requires editing
this file, no other logic module should contain literal values like these.

Pixel/panel/on-screen sizing constants live in display_config.py instead -
game logic has no notion of pixels, so nothing in this file does either.
No physical-distance unit (meters, m/s) appears anywhere in this file or
in realtime/physics either - the logic layer only ever deals in board
squares and plain millisecond durations, never a physical unit or an
asset-derived speed.
"""

EMPTY_TOKEN = "."

# Base real-time duration, in ms, for jump/short_rest/long_rest - states
# with no physical speed to derive a duration from (their
# physics.speed_m_per_sec is 0.0, they cover no distance). Game-design
# values, not read from any asset - realtime/physics must never derive a
# gameplay-affecting duration from how many sprite frames an animation
# happens to have, or from its frames_per_sec (both graphics-only
# concerns). These three numbers match this project's original
# animation-cycle-derived timing (5 frames at 8fps = 625ms for jump/
# short_rest, 5 frames at 6fps = 833ms for long_rest) at the point that
# dependency was removed, so gameplay feel is unchanged.
AIRBORNE_BASE_DURATION_MS = 625
SHORT_REST_BASE_DURATION_MS = 625
LONG_REST_BASE_DURATION_MS = 833

# Base real-time duration, in ms, for crossing one board square while
# moving. A game-design value, not derived from any asset or physical
# unit - same reasoning as the three durations above. Every piece kind
# happens to share this value today; a future kind with its own pace
# would get its own constant here, not a physics/speed lookup. Matches
# this project's original physics.speed_m_per_sec-derived timing (1.5 m/s
# over a 1-meter square) at the point that dependency was removed, so
# gameplay feel is unchanged.
MOVE_CELL_DURATION_MS = 667

# Raw short_rest/long_rest length was barely noticeable in a live playtest,
# so it's scaled up here to make the "can't act yet" window perceptible -
# gameplay-feel tuning, not derived from the assets.
REST_DURATION_MULTIPLIER = 1.5

# Raw jump hangtime is shorter than even the fastest attack, so a
# defensive jump could never still be airborne when the attack lands
# (found via live playtest - a frame-by-frame loop catches this timing
# gap that a single coarse test wait masks). 4x also has to cover the
# human reaction time between right-clicking to jump and the attacker
# completing a two-click select-then-target; 2x didn't leave enough
# margin to test reliably by hand.
AIRBORNE_DURATION_MULTIPLIER = 4.0

# Movement shapes, as (row, col) deltas - the piece rules read these
# instead of hardcoding direction/offset tuples of their own.
ROOK_DIRECTIONS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
BISHOP_DIRECTIONS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
QUEEN_DIRECTIONS = ROOK_DIRECTIONS + BISHOP_DIRECTIONS
KNIGHT_OFFSETS = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
KING_OFFSETS = QUEEN_DIRECTIONS
