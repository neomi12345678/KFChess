import time

import piece_config
from app import App, build_game
from boardio.board_parser import parse as parse_board
from display_config import compute_cell_size, screen_resolution_px, side_panel_width_for
from view.canvas.img_canvas import ImgCanvas
from view.canvas.window import GameWindow
from model.piece import BLACK, WHITE
from events.bus import ARRIVAL, GAME_STARTED, MOVE_LOGGED, Bus
from events.bus_bridge import BusBridge
from events.game_animations import GameAnimationCues
from events.observers import MoveLogObserver, ScoreObserver
from events.sound import SoundCues
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
#
# screen_size is injectable (see display_config.compute_cell_size) so tests
# can fix the "screen" instead of depending on whatever display this happens
# to run on - it defaults to the real OS query, used once here to size the
# whole board+panels layout for this launch (see view/canvas/window.py's
# fixed-size WINDOW_AUTOSIZE - nothing here re-sizes mid-game).
def build_app(
    white_name: str = "White",
    black_name: str = "Black",
    screen_size=screen_resolution_px,
    skin: piece_config.Skin = piece_config.DEFAULT_SKIN,
):
    board = parse_board(STARTING_BOARD)
    cell_size = compute_cell_size(board.width, board.height, screen_size=screen_size)
    side_panel_width_px = side_panel_width_for(cell_size)
    game_engine, controller, board_mapper = build_game(
        board, board_offset_x=side_panel_width_px, cell_size=cell_size
    )

    # The GUI's own moves-log/score/sound/animation display, not something
    # main.py's text-script runner needs, so it stays out of the shared
    # build_game wiring. Routed through events/bus.py's Bus rather than
    # registered as GameEngine observers directly - move_log/score/sound/
    # animations each subscribe to the topics they care about, and
    # BusBridge (the one actual GameObserver here) is all GameEngine itself
    # ever sees (see events/bus_bridge.py).
    move_log = MoveLogObserver(board_height=board.height)
    score = ScoreObserver()
    bus = Bus()
    bus.subscribe(MOVE_LOGGED, move_log.on_move_logged)
    bus.subscribe(ARRIVAL, move_log.on_arrival)
    bus.subscribe(ARRIVAL, score.on_arrival)
    sound_cues = SoundCues(bus)
    game_animation_cues = GameAnimationCues(bus)
    game_engine.add_observer(BusBridge(bus))
    bus.publish(GAME_STARTED)

    canvas = ImgCanvas(
        board_width=board.width,
        board_height=board.height,
        side_panel_width_px=side_panel_width_px,
        cell_size=cell_size,
        skin=skin,
    )
    renderer = Renderer(
        canvas,
        move_log=move_log,
        score=score,
        player_names={WHITE: white_name, BLACK: black_name},
        side_panel_width_px=side_panel_width_px,
        cell_size=cell_size,
    )
    app = App(controller=controller, game_engine=game_engine, renderer=renderer, board_mapper=board_mapper)
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
