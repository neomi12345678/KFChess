from app import App, build_game
from boardio.board_parser import parse
from model.position import Position


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


def test_build_game_with_no_board_offset_selects_the_piece_at_the_raw_pixel():
    board = parse("wK . .\n. . .\n. . .")
    game_engine, controller = build_game(board)

    controller.click(50, 50)

    assert controller.selected == Position(0, 0)


def test_build_game_threads_board_offset_x_into_the_board_mapper_it_builds():
    # Regression guard: play.py draws the board inset by SIDE_PANEL_WIDTH_PX
    # (see view/canvas/img_canvas.py) - a click at the raw, un-shifted pixel a
    # piece used to sit at must now miss (it's in the side panel), and the
    # shifted pixel must hit instead. Losing this wiring is what broke every
    # click/move in the running game after side panels were added.
    board = parse("wK . .\n. . .\n. . .")
    game_engine, controller = build_game(board, board_offset_x=260)

    controller.click(50, 50)
    assert controller.selected is None

    controller.click(260 + 50, 50)
    assert controller.selected == Position(0, 0)
