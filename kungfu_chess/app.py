class App:
    def __init__(self, controller, game_engine, renderer):
        self._controller = controller
        self._game_engine = game_engine
        self._renderer = renderer

    def on_click(self, x: int, y: int) -> None:
        self._controller.click(x, y)

    def render(self) -> None:
        snapshot = self._game_engine.snapshot(selected=self._controller.selected)
        self._renderer.draw(snapshot)
