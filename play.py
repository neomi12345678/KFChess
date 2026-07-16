import time

from app import App, build_game
from boardio.board_parser import parse as parse_board
from display_config import SIDE_PANEL_WIDTH_PX
from view.canvas.img_canvas import ImgCanvas
from view.canvas.window import GameWindow
from model.piece import BLACK, WHITE
from view.observers import MoveLogObserver, ScoreObserver
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


# Everything buildable without opening a real OS window - split out from
# main() so it's unit-testable on its own. GameWindow's constructor calls
# cv2.namedWindow, an actual side effect on the screen, and the loop below
# blocks on a real event queue - neither belongs in a test, real or faked;
# this function is the rest of main()'s wiring, minus those two things.
def build_app(white_name: str = "White", black_name: str = "Black"):
    board = parse_board(STARTING_BOARD)
    game_engine, controller = build_game(board, board_offset_x=SIDE_PANEL_WIDTH_PX)

    # Registered as GameEngine observers (see engine/game_engine.py's
    # add_observer) rather than wired into build_game - this is the GUI's
    # own moves-log/score display, not something main.py's text-script
    # runner needs, so it stays out of the shared build_game wiring.
    move_log = MoveLogObserver(board_height=board.height)
    score = ScoreObserver()
    game_engine.add_observer(move_log)
    game_engine.add_observer(score)

    canvas = ImgCanvas(board_width=board.width, board_height=board.height, side_panel_width_px=SIDE_PANEL_WIDTH_PX)
    renderer = Renderer(
        canvas,
        move_log=move_log,
        score=score,
        player_names={WHITE: white_name, BLACK: black_name},
        side_panel_width_px=SIDE_PANEL_WIDTH_PX,
    )
    app = App(controller=controller, game_engine=game_engine, renderer=renderer)
    return app, game_engine, canvas


def main(white_name: str = "White", black_name: str = "Black") -> None:  # pragma: no cover
    app, game_engine, canvas = build_app(white_name, black_name)

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


if __name__ == "__main__":  # pragma: no cover
    main()
