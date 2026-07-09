from dataclasses import dataclass, field
from typing import List, Tuple

from engine.game_engine import GameEngine
from boardio.board_parser import parse
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine
from view.renderer import Renderer


@dataclass
class FakeCanvas:
    rects: List[Tuple[int, int, int, int]] = field(default_factory=list)
    images: List[Tuple[str, int, int]] = field(default_factory=list)
    highlighted_cells: List[Tuple[int, int]] = field(default_factory=list)
    texts: List[str] = field(default_factory=list)

    def draw_rect(self, x, y, width, height):
        self.rects.append((x, y, width, height))

    def draw_image(self, name, x, y):
        self.images.append((name, x, y))

    def highlight_cell(self, row, col):
        self.highlighted_cells.append((row, col))

    def draw_text(self, text, x, y):
        self.texts.append(text)


def make_engine(board_text):
    board = parse(board_text)
    return board, GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=RealTimeArbiter(board))


def test_renderer_draws_the_board_grid_and_pieces_without_mutating_state():
    board, engine = make_engine("wK . .\n. . .\n. . bK")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()

    Renderer(canvas).draw(snapshot)

    assert len(canvas.rects) == 9
    assert len(canvas.images) == 2
    assert board.get_piece(Position(0, 0)) is not None
    assert board.get_piece(Position(2, 2)) is not None


def test_renderer_highlights_the_selected_cell():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot(selected=Position(0, 0))
    canvas = FakeCanvas()

    Renderer(canvas).draw(snapshot)

    assert canvas.highlighted_cells == [(0, 0)]


def test_renderer_draws_no_highlight_without_a_selection():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()

    Renderer(canvas).draw(snapshot)

    assert canvas.highlighted_cells == []


def test_renderer_shows_game_over_message():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    engine.game_over = True
    snapshot = engine.snapshot()
    canvas = FakeCanvas()

    Renderer(canvas).draw(snapshot)

    assert canvas.texts == ["Game Over"]
