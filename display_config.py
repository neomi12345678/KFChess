"""Presentation-only sizing constants - pixels, panels, on-screen layout.

Nothing under model/, rules/, physics/, realtime/, engine/, or boardio/
imports this module: game logic is defined in board-relative rows/columns
and never needs a pixel size. Only input/board_mapper.py (translating a
raw click into a cell) and the view/play.py side read this file -
see logic_config.py for the logic-side constants (durations, movement
shapes) that have no notion of pixels at all. Gameplay timing never
derives from a physical unit either (see logic_config.py's
MOVE_CELL_DURATION_MS) - the meters-to-pixels translation below exists
purely to size the board on screen, and stops at CELL_SIZE; nothing past
this file ever sees a meter.
"""

# How many on-screen pixels stand for one real-world meter, and how many
# meters wide a board square is drawn as - the two are only ever
# multiplied together into CELL_SIZE below, never read separately or
# passed anywhere else, so this is purely a rendering-scale decision, not
# a source either of these constants could feed a duration with. Chosen
# to reproduce this project's original CELL_SIZE (100px) exactly, so the
# board's on-screen size is unchanged.
PIXELS_PER_METER = 100
METERS_PER_SQUARE = 1.0

CELL_SIZE = round(PIXELS_PER_METER * METERS_PER_SQUARE)

# Width, in pixels, of each side panel (moves log/score/player name) the
# board is flanked by - see view/canvas/img_canvas.py's side_panel_width_px.
# 0 by default (ImgCanvas's own default) so anything that doesn't ask for
# panels gets a frame sized exactly to the board, unchanged. Also the
# reference ratio side_panel_width_for() scales from, alongside CELL_SIZE.
SIDE_PANEL_WIDTH_PX = 260

# How many of the most recent moves-log entries a side panel shows at once
# (see view/renderer.py) - older entries still exist in
# events.observers.MoveLogObserver, just scrolled out of what's drawn.
MAX_VISIBLE_MOVES_PER_PANEL = 30

# compute_cell_size fits the board (plus both side panels, at their usual
# proportion to a square) within this fraction of the actual screen -
# leaves a visible margin instead of a window that touches every screen
# edge exactly.
_SCREEN_FIT_FRACTION = 0.9
_MIN_CELL_SIZE_PX = 20


# Real screen-resolution query, Windows-only - same fallback style as
# view/canvas/window.py's _disable_windows_dpi_scaling: (None, None)
# whenever it can't be read (any other OS, or the OS call fails), so
# compute_cell_size below falls back to the fixed CELL_SIZE instead of
# crashing. Not unit-tested itself (a real OS call, no fake to inject into
# it) - see compute_cell_size for the injectable seam tests use instead.
def screen_resolution_px():  # pragma: no cover
    import sys

    if sys.platform != "win32":
        return None, None

    import ctypes

    try:
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except (AttributeError, OSError):
        return None, None


# Picks a CELL_SIZE that fits board_width x board_height squares, plus both
# side panels, within _SCREEN_FIT_FRACTION of the actual screen - decided
# once at process launch (see view/canvas/window.py's fixed-size
# WINDOW_AUTOSIZE; nothing here supports resizing mid-game), so the whole
# layout fits whatever screen is actually available instead of a
# hardcoded resolution. screen_size is injectable, like every other
# clock/randomness seam in this codebase (e.g. view/canvas/sprite_frames.py's
# SpriteAnimator), so tests can supply a fixed fake resolution instead of
# depending on the real display.
def compute_cell_size(board_width: int, board_height: int, screen_size=screen_resolution_px) -> int:
    screen_width, screen_height = screen_size()
    if screen_width is None or screen_height is None:
        return CELL_SIZE

    panel_width_in_cells = SIDE_PANEL_WIDTH_PX / CELL_SIZE
    height_limited = (screen_height * _SCREEN_FIT_FRACTION) / board_height
    width_limited = (screen_width * _SCREEN_FIT_FRACTION) / (board_width + 2 * panel_width_in_cells)

    return max(_MIN_CELL_SIZE_PX, round(min(height_limited, width_limited)))


# The side panel's own width scales together with a computed cell_size, at
# the same ratio SIDE_PANEL_WIDTH_PX has to CELL_SIZE - so a panel stays
# legible relative to the board instead of the board scaling while the
# panel stays pinned at a fixed pixel width.
def side_panel_width_for(cell_size: int) -> int:
    return round(SIDE_PANEL_WIDTH_PX / CELL_SIZE * cell_size)
