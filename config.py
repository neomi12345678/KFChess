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
