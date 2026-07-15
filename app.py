from engine.game_engine import GameEngine
from input.board_mapper import BoardMapper
from input.controller import Controller
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine


# Builds the engine + input layers for a parsed board - the one place both
# main.py's script runner and play.py's interactive window get this wiring
# from, so a constructor change to any of these only needs updating here.
#
# board_offset_x defaults to 0 (main.py's script runner has no window, let
# alone side panels) - play.py passes its actual SIDE_PANEL_WIDTH_PX so
# clicks on the visually-inset board (see graphics/img_canvas.py) map back
# to the right column instead of being read as raw, unshifted pixels.
def build_game(board, board_offset_x: int = 0):
    real_time_arbiter = RealTimeArbiter(board)
    game_engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=real_time_arbiter)
    board_mapper = BoardMapper(width=board.width, height=board.height, board_offset_x=board_offset_x)
    controller = Controller(board_mapper=board_mapper, game_engine=game_engine)
    return game_engine, controller


# Wires the interactive (non-CLI) surface together: clicks go to the
# controller, rendering reads back whatever state that produced.
class App:
    def __init__(self, controller, game_engine, renderer):
        self._controller = controller
        self._game_engine = game_engine
        self._renderer = renderer

    def on_click(self, x: int, y: int) -> None:
        self._controller.click(x, y)

    def on_jump(self, x: int, y: int) -> None:
        self._controller.jump(x, y)

    def render(self) -> None:
        snapshot = self._game_engine.snapshot(selected=self._controller.selected)
        self._renderer.draw(snapshot)
