"""Everything buildable without opening a real OS window - split out from
play.py's run loop so it's unit-testable on its own. GameWindow's
constructor (view/canvas/window.py) calls cv2.namedWindow, an actual side
effect on the screen, and play.py's main() loop blocks on a real event
queue - neither belongs in a test, real or faked; this module is the rest
of main()'s wiring, minus those two things.
"""

import piece_config
from app import App
from boardio.board_parser import parse as parse_board
from boardio.starting_position import STARTING_BOARD
from display_config import compute_cell_size, screen_resolution_px, side_panel_width_for
from engine.game_builder import build_game
from input.controller_builder import build_controller
from view.canvas.img_canvas import ImgCanvas
from model.game_state import ArrivalEvent, MoveLoggedEvent
from model.piece import BLACK, WHITE
from events.bus import Bus
from events.bus_bridge import BusBridge
from events.game_animations import GameAnimationCues
from events.game_events import GameStartedEvent
from events.observers import MoveLogObserver, ScoreObserver
from events.sound import SoundCues
from view.renderer import Renderer

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
    game_engine = build_game(board)
    controller, board_mapper = build_controller(
        game_engine, width=board.width, height=board.height, board_offset_x=side_panel_width_px, cell_size=cell_size
    )

    # The GUI's own moves-log/score/sound/animation display, not something
    # main.py's text-script runner needs, so it stays out of the shared
    # build_game wiring. Routed through events/bus.py's Bus rather than
    # registered as GameEngine observers directly - move_log/score/sound/
    # animations each subscribe to the event types they care about, and
    # BusBridge (the one actual GameObserver here) is all GameEngine itself
    # ever sees (see events/bus_bridge.py).
    move_log = MoveLogObserver(board_height=board.height)
    score = ScoreObserver()
    bus = Bus()
    bus.subscribe(MoveLoggedEvent, move_log.on_move_logged)
    bus.subscribe(ArrivalEvent, move_log.on_arrival)
    bus.subscribe(ArrivalEvent, score.on_arrival)
    sound_cues = SoundCues(bus)
    game_animation_cues = GameAnimationCues(bus)
    game_engine.add_observer(BusBridge(bus))
    bus.publish(GameStartedEvent())

    canvas = ImgCanvas(
        board_width=board.width,
        board_height=board.height,
        side_panel_width_px=side_panel_width_px,
        cell_size=cell_size,
        skin=skin,
    )
    renderer = Renderer(
        canvas,
        player_names={WHITE: white_name, BLACK: black_name},
        side_panel_width_px=side_panel_width_px,
        cell_size=cell_size,
    )
    app = App(
        controller=controller, game_engine=game_engine, renderer=renderer, board_mapper=board_mapper,
        move_log=move_log, score=score,
    )
    return app, game_engine, canvas
