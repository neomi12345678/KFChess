from app import App
from boardio.board_parser import parse
from engine.game_builder import build_game
from input.board_mapper import BoardMapper
from input.controller_builder import build_controller
from model.position import Position
from view.ui_snapshot import build_ui_snapshot


class SpyController:
    def __init__(self):
        self.clicks = []
        self.jumps = []
        self.selected = None

    def click(self, cell):
        self.clicks.append(cell)

    def jump(self, cell):
        self.jumps.append(cell)


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

    def draw(self, ui_snapshot):
        self.drawn.append(ui_snapshot)


def test_on_click_routes_the_resolved_cell_to_controller_click():
    controller = SpyController()
    board_mapper = BoardMapper(width=3, height=3)
    app = App(controller=controller, game_engine=None, renderer=None, board_mapper=board_mapper)

    app.on_click(150, 250)

    assert controller.clicks == [Position(2, 1)]


def test_on_jump_routes_the_resolved_cell_to_controller_jump():
    controller = SpyController()
    board_mapper = BoardMapper(width=3, height=3)
    app = App(controller=controller, game_engine=None, renderer=None, board_mapper=board_mapper)

    app.on_jump(150, 250)

    assert controller.jumps == [Position(2, 1)]


def test_on_click_outside_the_board_routes_none_to_controller_click():
    controller = SpyController()
    board_mapper = BoardMapper(width=3, height=3)
    app = App(controller=controller, game_engine=None, renderer=None, board_mapper=board_mapper)

    app.on_click(-10, 50)

    assert controller.clicks == [None]


def test_render_draws_a_snapshot_built_with_the_current_selection():
    controller = SpyController()
    controller.selected = "some-cell"
    snapshot = object()
    game_engine = FakeGameEngine(snapshot)
    renderer = SpyRenderer()
    board_mapper = BoardMapper(width=3, height=3)
    app = App(controller=controller, game_engine=game_engine, renderer=renderer, board_mapper=board_mapper)

    app.render()

    assert game_engine.snapshot_calls == ["some-cell"]
    assert renderer.drawn == [build_ui_snapshot(snapshot)]


def test_build_game_with_no_board_offset_selects_the_piece_at_the_raw_pixel():
    board = parse("wK . .\n. . .\n. . .")
    game_engine = build_game(board)
    controller, board_mapper = build_controller(game_engine, width=board.width, height=board.height)
    app = App(controller=controller, game_engine=game_engine, renderer=None, board_mapper=board_mapper)

    app.on_click(50, 50)

    assert controller.selected == Position(0, 0)


def test_build_game_threads_board_offset_x_into_the_board_mapper_it_builds():
    # Regression guard: play.py draws the board inset by SIDE_PANEL_WIDTH_PX
    # (see view/canvas/img_canvas.py) - a click at the raw, un-shifted pixel a
    # piece used to sit at must now miss (it's in the side panel), and the
    # shifted pixel must hit instead. Losing this wiring is what broke every
    # click/move in the running game after side panels were added.
    board = parse("wK . .\n. . .\n. . .")
    game_engine = build_game(board)
    controller, board_mapper = build_controller(game_engine, width=board.width, height=board.height, board_offset_x=260)
    app = App(controller=controller, game_engine=game_engine, renderer=None, board_mapper=board_mapper)

    app.on_click(50, 50)
    assert controller.selected is None

    app.on_click(260 + 50, 50)
    assert controller.selected == Position(0, 0)
