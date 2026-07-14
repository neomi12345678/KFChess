import time

from app import App, build_game
from boardio.board_parser import parse as parse_board
from graphics.img_canvas import ImgCanvas
from graphics.window import GameWindow
from view.renderer import Renderer

STARTING_BOARD = """
bR bN bB bQ bK bB bN bR
bP bP bP bP bP bP bP bP
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
wP wP wP wP wP wP wP wP
wR wN wB wQ wK wB wN wR
""".strip()


def main() -> None:
    board = parse_board(STARTING_BOARD)
    game_engine, controller = build_game(board)
    canvas = ImgCanvas(board_width=board.width, board_height=board.height)
    app = App(controller=controller, game_engine=game_engine, renderer=Renderer(canvas))

    window = GameWindow("KFChess")
    window.on_click(app.on_click)
    window.on_jump(app.on_jump)

    last_tick = time.monotonic()
    # Truncating each frame's elapsed time to whole milliseconds and
    # discarding the remainder would make the simulated clock drift behind
    # the wall clock - carry the fractional remainder into the next frame
    # instead so nothing is lost.
    carried_ms = 0.0
    running = True
    while running:
        now = time.monotonic()
        elapsed_ms = (now - last_tick) * 1000 + carried_ms
        whole_ms = int(elapsed_ms)
        carried_ms = elapsed_ms - whole_ms
        last_tick = now
        game_engine.wait(whole_ms)

        canvas.begin_frame()
        app.render()
        running = window.show(canvas.frame())

    window.close()


if __name__ == "__main__":
    main()
