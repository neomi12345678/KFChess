from view.ui_snapshot import build_ui_snapshot


# Wires the interactive (non-CLI) surface together: clicks go to the
# controller, rendering reads back whatever state that produced.
#
# board_mapper lives here, not in Controller - App is the GUI boundary that
# receives raw window pixels (see view/canvas/window.py's GameWindow), and
# translates them into board cells before Controller ever sees them, so
# Controller itself never has any notion of pixels (see input/controller.py).
class App:
    # move_log/score default to None (no side panels), the same default
    # view/renderer.py's Renderer used to hold itself - now App is the one
    # place that reaches into them, once per frame, to build the UiSnapshot
    # Renderer.draw actually consumes (see view/ui_snapshot.py).
    def __init__(self, controller, game_engine, renderer, board_mapper, move_log=None, score=None):
        self._controller = controller
        self._game_engine = game_engine
        self._renderer = renderer
        self._board_mapper = board_mapper
        self._move_log = move_log
        self._score = score

    def on_click(self, x: int, y: int) -> None:
        self._controller.click(self._board_mapper.pixel_to_cell(x, y))

    def on_jump(self, x: int, y: int) -> None:
        self._controller.jump(self._board_mapper.pixel_to_cell(x, y))

    def render(self) -> None:
        snapshot = self._game_engine.snapshot(selected=self._controller.selected)
        ui_snapshot = build_ui_snapshot(snapshot, move_log=self._move_log, score=self._score)
        self._renderer.draw(ui_snapshot)
