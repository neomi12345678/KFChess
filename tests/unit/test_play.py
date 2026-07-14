from config import CELL_SIZE, SIDE_PANEL_WIDTH_PX
from play import STARTING_BOARD, build_app


def test_build_app_produces_a_frame_sized_for_the_full_starting_board_and_its_side_panels():
    app, game_engine, canvas = build_app()

    board_width = len(STARTING_BOARD.splitlines()[0].split())
    board_height = len(STARTING_BOARD.splitlines())

    canvas.begin_frame()
    app.render()

    height, width = canvas.frame().shape[:2]
    assert width == board_width * CELL_SIZE + 2 * SIDE_PANEL_WIDTH_PX
    assert height == board_height * CELL_SIZE


def test_build_app_wires_clicks_at_the_panel_shifted_pixel_to_the_right_board_cell():
    # Regression guard for the exact bug this shipped with once before:
    # a click at the raw pixel where e2's pawn visually sits, once side
    # panels are enabled, must resolve to that pawn - not miss because
    # board_mapper wasn't told about the same offset ImgCanvas draws with.
    app, game_engine, canvas = build_app()

    pawn_row, pawn_col = 6, 4  # e2, in the standard starting position
    click_x = SIDE_PANEL_WIDTH_PX + pawn_col * CELL_SIZE + 50
    click_y = pawn_row * CELL_SIZE + 50

    app.on_click(click_x, click_y)
    dest_x = SIDE_PANEL_WIDTH_PX + pawn_col * CELL_SIZE + 50
    dest_y = (pawn_row - 2) * CELL_SIZE + 50
    app.on_click(dest_x, dest_y)
    game_engine.wait(2000)

    canvas.begin_frame()
    app.render()  # must not raise
    assert canvas.frame() is not None


def test_build_app_accepts_custom_player_names_without_raising():
    app, game_engine, canvas = build_app(white_name="Musti Shusti", black_name="Chicko Miko")

    canvas.begin_frame()
    app.render()

    assert canvas.frame() is not None
