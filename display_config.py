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
# panels gets a frame sized exactly to the board, unchanged.
SIDE_PANEL_WIDTH_PX = 260

# How many of the most recent moves-log entries a side panel shows at once
# (see view/renderer.py) - older entries still exist in
# view.observers.MoveLogObserver, just scrolled out of what's drawn.
MAX_VISIBLE_MOVES_PER_PANEL = 30
