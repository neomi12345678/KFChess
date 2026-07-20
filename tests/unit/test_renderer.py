from dataclasses import dataclass, field
from typing import List, Tuple

from engine.game_engine import GameEngine
from boardio.board_parser import parse
from model.game_state import MoveLoggedEvent
from model.piece import BLACK, PAWN, WHITE
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine
from events.observers import MoveLogObserver, ScoreObserver
from view.renderer import Renderer
from view.ui_snapshot import build_ui_snapshot


@dataclass
class FakeCanvas:
    rects: List[Tuple[int, int, int, int]] = field(default_factory=list)
    images: List[Tuple[str, int, int]] = field(default_factory=list)
    highlighted_cells: List[Tuple[int, int]] = field(default_factory=list)
    texts: List[str] = field(default_factory=list)
    # (text, x) pairs, in addition to `texts` above - new panel-placement
    # tests need the x each line was drawn at; existing tests only ever
    # assert on `texts` itself, so that stays a plain list of strings.
    text_positions: List[Tuple[str, int]] = field(default_factory=list)

    def draw_rect(self, x, y, width, height):
        self.rects.append((x, y, width, height))

    def draw_image(self, name, x, y):
        self.images.append((name, x, y))

    def highlight_cell(self, row, col):
        self.highlighted_cells.append((row, col))

    def draw_text(self, text, x, y, font_size=1.0, color=(255, 255, 255, 255)):
        self.texts.append(text)
        self.text_positions.append((text, x))


def make_engine(board_text):
    board = parse(board_text)
    return board, GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=RealTimeArbiter(board))


def test_renderer_draws_the_board_grid_and_pieces_without_mutating_state():
    board, engine = make_engine("wK . .\n. . .\n. . bK")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()

    Renderer(canvas).draw(build_ui_snapshot(snapshot))

    assert len(canvas.rects) == 9
    assert len(canvas.images) == 2
    assert board.get_piece(Position(0, 0)) is not None
    assert board.get_piece(Position(2, 2)) is not None


def test_renderer_encodes_piece_id_color_kind_and_state_in_the_draw_image_key():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()

    Renderer(canvas).draw(build_ui_snapshot(snapshot))

    king = board.get_piece(Position(0, 0))
    [(key, _, _)] = canvas.images
    assert key == f"{king.id}:white:king:idle"


def test_renderer_highlights_the_selected_cell():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot(selected=Position(0, 0))
    canvas = FakeCanvas()

    Renderer(canvas).draw(build_ui_snapshot(snapshot))

    assert canvas.highlighted_cells == [(0, 0)]


def test_renderer_draws_no_highlight_without_a_selection():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()

    Renderer(canvas).draw(build_ui_snapshot(snapshot))

    assert canvas.highlighted_cells == []


def test_renderer_shows_game_over_message():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    engine.game_over = True
    snapshot = engine.snapshot()
    canvas = FakeCanvas()

    Renderer(canvas).draw(build_ui_snapshot(snapshot))

    assert canvas.texts == ["Game Over"]


def test_renderer_draws_a_status_message_when_given_one():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()

    Renderer(canvas).draw(
        build_ui_snapshot(snapshot, status_message="Opponent disconnected - resigning in 5s unless they return")
    )

    assert "Opponent disconnected - resigning in 5s unless they return" in canvas.texts


def test_renderer_draws_no_status_message_by_default():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()

    Renderer(canvas).draw(build_ui_snapshot(snapshot))

    assert canvas.texts == []


def test_renderer_draws_game_over_and_status_message_on_separate_lines():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    engine.game_over = True
    snapshot = engine.snapshot()
    canvas = FakeCanvas()

    Renderer(canvas).draw(
        build_ui_snapshot(snapshot, status_message="Opponent disconnected - resigning in 0s unless they return")
    )

    assert canvas.texts == ["Game Over", "Opponent disconnected - resigning in 0s unless they return"]


def test_renderer_draws_no_panel_text_when_side_panels_are_not_configured():
    # side_panel_width_px defaults to 0 - a Renderer that never asked for
    # panels must behave exactly as it did before panels existed, even if
    # (mistakenly) given a UiSnapshot with move_log/score data anyway.
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()
    ui_snapshot = build_ui_snapshot(snapshot, move_log=MoveLogObserver(board_height=3), score=ScoreObserver())

    Renderer(canvas).draw(ui_snapshot)

    assert canvas.texts == []


def test_renderer_draws_default_name_and_zero_score_when_no_observers_are_given():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()

    Renderer(canvas, side_panel_width_px=200).draw(build_ui_snapshot(snapshot))

    assert "White" in canvas.texts
    assert "Black" in canvas.texts
    assert canvas.texts.count("Score: 0") == 2


def test_renderer_draws_player_names_and_score_from_the_given_observers():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()
    score = ScoreObserver()
    score.on_arrival(_arrival_with_capture())

    Renderer(
        canvas,
        player_names={WHITE: "Musti Shusti", BLACK: "Chicko Miko"},
        side_panel_width_px=200,
    ).draw(build_ui_snapshot(snapshot, score=score))

    assert "Musti Shusti" in canvas.texts
    assert "Chicko Miko" in canvas.texts
    assert "Score: 1" in canvas.texts


def _pawn_move_event(color, source, destination, elapsed_ms=0, piece_id="mover"):
    return MoveLoggedEvent(
        piece_id=piece_id,
        color=color,
        kind=PAWN,
        source=source,
        destination=destination,
        is_capture=False,
        is_jump=False,
        elapsed_ms=elapsed_ms,
    )


def test_renderer_draws_move_log_entries_for_each_color_with_formatted_time():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()
    # MoveLogObserver's own board_height is independent of the tiny 3x3
    # board this test's Renderer/snapshot uses - it only drives notation.
    move_log = MoveLogObserver(board_height=8)
    move_log.on_move_logged(_pawn_move_event(WHITE, Position(6, 4), Position(4, 4), elapsed_ms=4105))

    Renderer(canvas, side_panel_width_px=200).draw(build_ui_snapshot(snapshot, move_log=move_log))

    assert "00:04.105  e4" in canvas.texts


def test_renderer_only_shows_the_most_recent_moves_up_to_the_configured_limit():
    board, engine = make_engine("wK . .\n. . .\n. . .")
    snapshot = engine.snapshot()
    canvas = FakeCanvas()
    move_log = MoveLogObserver(board_height=8)
    for i in range(5):
        move_log.on_move_logged(_pawn_move_event(WHITE, Position(6, i), Position(4, i), elapsed_ms=i))

    Renderer(canvas, side_panel_width_px=200, max_visible_moves=2).draw(build_ui_snapshot(snapshot, move_log=move_log))

    shown = [text for text in canvas.texts if text.startswith("00:00.00") and len(text) > len("00:00.000")]
    assert shown == ["00:00.003  d4", "00:00.004  e4"]


def test_renderer_draws_blacks_panel_on_the_left_and_whites_on_the_right():
    board, engine = make_engine("wK . .\n. . .\n. . .")  # 3 columns * CELL_SIZE = 300px board
    snapshot = engine.snapshot()
    canvas = FakeCanvas()
    move_log = MoveLogObserver(board_height=8)
    move_log.on_move_logged(_pawn_move_event(BLACK, Position(1, 4), Position(3, 4)))
    move_log.on_move_logged(_pawn_move_event(WHITE, Position(6, 4), Position(4, 4)))

    Renderer(canvas, side_panel_width_px=200).draw(build_ui_snapshot(snapshot, move_log=move_log))

    black_x = dict(canvas.text_positions)["00:00.000  e5"]
    white_x = dict(canvas.text_positions)["00:00.000  e4"]
    assert black_x == 10
    assert white_x == 200 + 3 * 100 + 10  # side_panel_width_px + board_px_width + margin


def _arrival_with_capture():
    from model.game_state import ArrivalEvent
    from model.piece import PAWN, Piece

    attacker = Piece(id="atk", color=WHITE, kind=PAWN, cell=Position(0, 0))
    captured = Piece(id="cap", color=BLACK, kind=PAWN, cell=Position(0, 1))
    return ArrivalEvent(piece=attacker, captured_piece=captured)
