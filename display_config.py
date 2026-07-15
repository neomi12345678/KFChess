"""Presentation-only sizing constants - pixels, panels, on-screen layout.

Nothing under model/, rules/, physics/, realtime/, engine/, or boardio/
imports this module: game logic is defined in board-relative rows/columns
and never needs a pixel size. Only input/board_mapper.py (translating a
raw click into a cell) and the view/graphics/play.py side read this file -
see logic_config.py for the logic-side constants (durations, meters, movement
shapes) that have no notion of pixels at all.
"""

CELL_SIZE = 100

# Width, in pixels, of each side panel (moves log/score/player name) the
# board is flanked by - see graphics/img_canvas.py's side_panel_width_px.
# 0 by default (ImgCanvas's own default) so anything that doesn't ask for
# panels gets a frame sized exactly to the board, unchanged.
SIDE_PANEL_WIDTH_PX = 260

# How many of the most recent moves-log entries a side panel shows at once
# (see view/renderer.py) - older entries still exist in
# view.observers.MoveLogObserver, just scrolled out of what's drawn.
MAX_VISIBLE_MOVES_PER_PANEL = 30
