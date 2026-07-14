from app import App


class SpyController:
    def __init__(self):
        self.clicks = []
        self.jumps = []
        self.selected = None

    def click(self, x, y):
        self.clicks.append((x, y))

    def jump(self, x, y):
        self.jumps.append((x, y))


class FakeGameEngine:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.snapshot_calls = []

    def snapshot(self, selected):
        self.snapshot_calls.append(selected)
        return self._snapshot


class SpyRenderer:
    def __init__(self):
        self.drawn = []

    def draw(self, snapshot):
        self.drawn.append(snapshot)


def test_on_click_routes_to_controller_click():
    controller = SpyController()
    app = App(controller=controller, game_engine=None, renderer=None)

    app.on_click(150, 250)

    assert controller.clicks == [(150, 250)]


def test_on_jump_routes_to_controller_jump():
    controller = SpyController()
    app = App(controller=controller, game_engine=None, renderer=None)

    app.on_jump(150, 250)

    assert controller.jumps == [(150, 250)]


def test_render_draws_a_snapshot_built_with_the_current_selection():
    controller = SpyController()
    controller.selected = "some-cell"
    snapshot = object()
    game_engine = FakeGameEngine(snapshot)
    renderer = SpyRenderer()
    app = App(controller=controller, game_engine=game_engine, renderer=renderer)

    app.render()

    assert game_engine.snapshot_calls == ["some-cell"]
    assert renderer.drawn == [snapshot]
