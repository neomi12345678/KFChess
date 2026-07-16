"""Manual visual check that mouse pixel coordinates map to the right board
cell (input/board_mapper.py's BoardMapper, view/canvas/img_canvas.py's
ImgCanvas) - not an automated test, a debug tool you run and eyeball.

Hover highlights the cell currently under the cursor in yellow; clicking
highlights the clicked cell in red instead, so it stays visible after you
move the mouse away. If both always agree with where the cursor visually
is on the board, pixel->cell mapping is correct.

Run directly: `python debug_mouse.py`. Esc or closing the window exits.
"""

from input.board_mapper import BoardMapper
from view.canvas.img_canvas import ImgCanvas
from view.canvas.window import GameWindow

BOARD_WIDTH = 8
BOARD_HEIGHT = 8

HOVER_COLOR = (0, 255, 255)  # yellow
CLICK_COLOR = (0, 0, 255)  # red


# Opens a real window (see view/canvas/window.py) - not unit-tested for the
# same reason GameWindow itself isn't.
def main() -> None:  # pragma: no cover
    mapper = BoardMapper(width=BOARD_WIDTH, height=BOARD_HEIGHT)
    canvas = ImgCanvas(board_width=BOARD_WIDTH, board_height=BOARD_HEIGHT)
    window = GameWindow("Mouse Mapping Debug")

    state = {"hovered": None, "clicked": None}
    window.on_move(lambda x, y: state.__setitem__("hovered", mapper.pixel_to_cell(x, y)))
    window.on_click(lambda x, y: state.__setitem__("clicked", mapper.pixel_to_cell(x, y)))

    running = True
    while running:
        canvas.begin_frame()
        if state["hovered"] is not None:
            canvas.highlight_cell(row=state["hovered"].row, col=state["hovered"].col, color=HOVER_COLOR, alpha=0.35)
        if state["clicked"] is not None:
            canvas.highlight_cell(row=state["clicked"].row, col=state["clicked"].col, color=CLICK_COLOR, alpha=0.5)
        running = window.show(canvas.frame())

    window.close()


if __name__ == "__main__":  # pragma: no cover
    main()
