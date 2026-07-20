from display_config import CELL_SIZE
from engine.game_engine import GameEngine
from input.controller_builder import build_controller
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine


# Builds the engine + input layers for a parsed board - the one place both
# main.py's script runner and play.py's interactive window get this wiring
# from, so a constructor change to any of these only needs updating here.
#
# board_offset_x defaults to 0 (main.py's script runner has no window, let
# alone side panels) - play.py passes its actual, screen-derived panel width
# (see display_config.side_panel_width_for) so clicks on the visually-inset
# board (see view/canvas/img_canvas.py) map back to the right column instead
# of being read as raw, unshifted pixels. cell_size similarly defaults to
# the fixed CELL_SIZE but lets play.py thread through whatever
# display_config.compute_cell_size decided for the actual screen at launch.
def build_game(board, board_offset_x: int = 0, cell_size: int = CELL_SIZE):
    real_time_arbiter = RealTimeArbiter(board)
    game_engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=real_time_arbiter)
    controller, board_mapper = build_controller(
        game_engine, width=board.width, height=board.height, board_offset_x=board_offset_x, cell_size=cell_size
    )
    return game_engine, controller, board_mapper


# Wires the interactive (non-CLI) surface together: clicks go to the
# controller, rendering reads back whatever state that produced.
#
# board_mapper lives here, not in Controller - App is the GUI boundary that
# receives raw window pixels (see view/canvas/window.py's GameWindow), and
# translates them into board cells before Controller ever sees them, so
# Controller itself never has any notion of pixels (see input/controller.py).
class App:
    def __init__(self, controller, game_engine, renderer, board_mapper):
        self._controller = controller
        self._game_engine = game_engine
        self._renderer = renderer
        self._board_mapper = board_mapper

    def on_click(self, x: int, y: int) -> None:
        self._controller.click(self._board_mapper.pixel_to_cell(x, y))

    def on_jump(self, x: int, y: int) -> None:
        self._controller.jump(self._board_mapper.pixel_to_cell(x, y))

    def render(self) -> None:
        snapshot = self._game_engine.snapshot(selected=self._controller.selected)
        self._renderer.draw(snapshot)
