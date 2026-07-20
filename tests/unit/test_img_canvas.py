import numpy as np

import piece_config
from boardio.board_parser import parse
from display_config import CELL_SIZE
from engine.game_engine import GameEngine
from view.canvas.img_canvas import ImgCanvas
from model.piece import COLOR_BY_LETTER, KIND_BY_LETTER
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine
from view.renderer import Renderer


def test_piece_code_covers_every_kind_and_color_and_points_at_a_real_asset_folder():
    # Real asset folder names on disk, compared as exact strings rather than
    # via Path.is_dir() - Windows' case-insensitive filesystem would let a
    # wrong-case code (e.g. "Rw" instead of "RW") resolve anyway and mask a
    # real bug that breaks on case-sensitive filesystems (Linux/Mac).
    actual_folder_names = {p.name for p in piece_config.PIECES_DIR.iterdir()}

    for kind_letter, kind_word in KIND_BY_LETTER.items():
        for color_letter, color_word in COLOR_BY_LETTER.items():
            code = piece_config.piece_code(kind_word, color_word)

            assert code == f"{kind_letter}{color_letter.upper()}"
            assert code in actual_folder_names


def test_begin_frame_resets_any_drawing_from_the_previous_frame():
    canvas = ImgCanvas()
    canvas.begin_frame()
    canvas.highlight_cell(row=0, col=0)
    painted = canvas.frame().copy()

    canvas.begin_frame()

    assert not np.array_equal(canvas.frame(), painted)


def test_draw_rect_does_not_modify_the_frame():
    canvas = ImgCanvas()
    canvas.begin_frame()
    before = canvas.frame().copy()

    canvas.draw_rect(x=0, y=0, width=CELL_SIZE, height=CELL_SIZE)

    assert np.array_equal(canvas.frame(), before)


def test_highlight_cell_blends_the_requested_color_into_only_that_cells_region():
    canvas = ImgCanvas()
    canvas.begin_frame()
    before = canvas.frame().copy()

    canvas.highlight_cell(row=0, col=0, color=(0, 255, 255), alpha=0.5)

    region_before = before[0:CELL_SIZE, 0:CELL_SIZE, :3].astype(float)
    expected_region = 0.5 * region_before + 0.5 * np.array([0, 255, 255])
    actual_region = canvas.frame()[0:CELL_SIZE, 0:CELL_SIZE, :3].astype(float)
    assert np.allclose(actual_region, expected_region, atol=1.0)

    # A neighboring cell is untouched.
    neighbor_before = before[0:CELL_SIZE, CELL_SIZE:2 * CELL_SIZE]
    neighbor_after = canvas.frame()[0:CELL_SIZE, CELL_SIZE:2 * CELL_SIZE]
    assert np.array_equal(neighbor_before, neighbor_after)


def test_draw_image_paints_the_piece_sprite_onto_the_frame():
    canvas = ImgCanvas()
    canvas.begin_frame()
    before = canvas.frame().copy()

    center_x, center_y = CELL_SIZE // 2, CELL_SIZE // 2
    canvas.draw_image("p1:white:king:idle", x=center_x, y=center_y)

    region_before = before[0:CELL_SIZE, 0:CELL_SIZE]
    region_after = canvas.frame()[0:CELL_SIZE, 0:CELL_SIZE]
    assert not np.array_equal(region_before, region_after)


# assets/pieces1_debug is a real, complete alternate piece set already on
# disk - proves ImgCanvas(skin=...) actually threads the skin down through
# SpriteAnimator to piece_config.load_animation end to end, not just that
# the constructor accepts the argument.
def test_draw_image_uses_the_given_skins_pieces_dir():
    debug_skin = piece_config.Skin(
        pieces_dir=piece_config.ASSETS_DIR / "pieces1_debug",
        board_path=piece_config.DEFAULT_SKIN.board_path,
    )
    canvas = ImgCanvas(skin=debug_skin)
    canvas.begin_frame()
    before = canvas.frame().copy()

    center_x, center_y = CELL_SIZE // 2, CELL_SIZE // 2
    canvas.draw_image("p1:white:king:idle", x=center_x, y=center_y)

    region_before = before[0:CELL_SIZE, 0:CELL_SIZE]
    region_after = canvas.frame()[0:CELL_SIZE, 0:CELL_SIZE]
    assert not np.array_equal(region_before, region_after)


def test_draw_text_does_not_raise_and_changes_the_frame():
    canvas = ImgCanvas()
    canvas.begin_frame()
    before = canvas.frame().copy()

    canvas.draw_text("Game Over", x=10, y=10)

    assert not np.array_equal(canvas.frame(), before)


def test_draw_text_is_visible_within_the_frame_even_at_y_zero():
    # Renderer draws "Game Over" at y=0 (view/renderer.py) - cv2.putText
    # treats (x, y) as the text's baseline, so without compensation the
    # glyphs would be clipped entirely above row 0 and never show up.
    canvas = ImgCanvas()
    canvas.begin_frame()
    before = canvas.frame().copy()

    canvas.draw_text("Game Over", x=0, y=0)

    assert not np.array_equal(canvas.frame()[0:40, 0:200], before[0:40, 0:200])


def test_renderer_and_img_canvas_integrate_end_to_end_for_a_real_snapshot():
    # Renderer builds the draw_image key and ImgCanvas parses it back apart
    # (view/canvas/img_canvas.py's key.split(":")) - exercised here with a key
    # Renderer actually produced, not one hand-written for a single method.
    board = parse("wK . .\n. . .\n. . bK")
    engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=RealTimeArbiter(board))
    canvas = ImgCanvas(board_width=board.width, board_height=board.height)
    canvas.begin_frame()

    Renderer(canvas).draw(engine.snapshot(selected=Position(0, 0)))

    assert canvas.frame() is not None


def test_side_panel_width_px_defaults_to_zero_and_leaves_the_frame_board_sized():
    canvas = ImgCanvas(board_width=3, board_height=3)
    canvas.begin_frame()

    assert canvas.frame().shape[1] == 3 * CELL_SIZE


def test_side_panel_width_px_widens_the_frame_by_twice_the_panel_width():
    canvas = ImgCanvas(board_width=3, board_height=3, side_panel_width_px=200)
    canvas.begin_frame()

    assert canvas.frame().shape[1] == 3 * CELL_SIZE + 2 * 200
    assert canvas.frame().shape[0] == 3 * CELL_SIZE


def test_side_panel_area_is_a_solid_opaque_background_not_transparent():
    canvas = ImgCanvas(board_width=3, board_height=3, side_panel_width_px=200)
    canvas.begin_frame()

    left_panel_pixel = canvas.frame()[0, 0]
    assert left_panel_pixel[3] == 255  # fully opaque alpha, not left as 0


def test_highlight_cell_is_shifted_right_by_the_side_panel_width():
    # Board-relative draws (highlight_cell/draw_image) must land on the
    # actual board, which is now inset by side_panel_width_px - not at the
    # raw column*CELL_SIZE offset from the frame's own left edge.
    canvas = ImgCanvas(board_width=3, board_height=3, side_panel_width_px=200)
    canvas.begin_frame()
    before = canvas.frame().copy()

    canvas.highlight_cell(row=0, col=0, color=(0, 255, 255), alpha=0.5)

    # The panel region (before the board even starts) is untouched.
    assert np.array_equal(canvas.frame()[:, 0:200], before[:, 0:200])
    # The actual board's first cell, now offset by the panel width, changed.
    assert not np.array_equal(
        canvas.frame()[0:CELL_SIZE, 200:200 + CELL_SIZE],
        before[0:CELL_SIZE, 200:200 + CELL_SIZE],
    )


def test_begin_frame_forgets_animation_state_for_a_piece_no_longer_drawn():
    # Regression guard for the wiring itself - view/piece_state_machine.py's
    # actual pruning logic (and its effect on which sprite frame comes back)
    # is covered directly in test_piece_state_machine.py and
    # test_sprite_frames.py. This only proves ImgCanvas.begin_frame() feeds
    # the animator the previous frame's drawn piece_ids and doesn't raise
    # once a previously-drawn piece (e.g. captured) stops being drawn.
    canvas = ImgCanvas()
    canvas.begin_frame()
    canvas.draw_image("p1:white:king:idle", x=CELL_SIZE // 2, y=CELL_SIZE // 2)

    canvas.begin_frame()  # p1 not drawn this frame - pruned on the next begin_frame
    canvas.begin_frame()  # must not raise even though p1 never reappears


def test_draw_image_is_shifted_right_by_the_side_panel_width():
    canvas = ImgCanvas(board_width=3, board_height=3, side_panel_width_px=200)
    canvas.begin_frame()
    before = canvas.frame().copy()

    center_x, center_y = CELL_SIZE // 2, CELL_SIZE // 2
    canvas.draw_image("p1:white:king:idle", x=center_x, y=center_y)

    assert np.array_equal(canvas.frame()[:, 0:200], before[:, 0:200])
    assert not np.array_equal(
        canvas.frame()[0:CELL_SIZE, 200:200 + CELL_SIZE],
        before[0:CELL_SIZE, 200:200 + CELL_SIZE],
    )
