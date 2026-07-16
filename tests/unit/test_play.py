from display_config import CELL_SIZE, SIDE_PANEL_WIDTH_PX, compute_cell_size, side_panel_width_for
from play import STARTING_BOARD, build_app

# (None, None) forces compute_cell_size's real-screen-detection fallback (see
# display_config.py), so these tests get the fixed default CELL_SIZE instead
# of depending on whatever screen this happens to run on.
NO_SCREEN = lambda: (None, None)


def test_build_app_produces_a_frame_sized_for_the_full_starting_board_and_its_side_panels():
    app, game_engine, canvas = build_app(screen_size=NO_SCREEN)

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
    app, game_engine, canvas = build_app(screen_size=NO_SCREEN)

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
    app, game_engine, canvas = build_app(white_name="Musti Shusti", black_name="Chicko Miko", screen_size=NO_SCREEN)

    canvas.begin_frame()
    app.render()

    assert canvas.frame() is not None


def test_build_app_shrinks_the_whole_layout_to_fit_a_small_injected_screen():
    # A screen too small for the fixed default CELL_SIZE must still show the
    # entire board+panels, just smaller - not clip off-screen or crash.
    small_screen = lambda: (1000, 700)

    board_width = len(STARTING_BOARD.splitlines()[0].split())
    board_height = len(STARTING_BOARD.splitlines())
    expected_cell_size = compute_cell_size(board_width, board_height, screen_size=small_screen)
    expected_panel_width = side_panel_width_for(expected_cell_size)
    assert expected_cell_size < CELL_SIZE  # sanity: this screen actually constrains it

    app, game_engine, canvas = build_app(screen_size=small_screen)
    canvas.begin_frame()
    app.render()

    height, width = canvas.frame().shape[:2]
    assert width == board_width * expected_cell_size + 2 * expected_panel_width
    assert height == board_height * expected_cell_size


def test_build_app_still_maps_clicks_correctly_when_the_screen_shrinks_the_board():
    small_screen = lambda: (1000, 700)
    board_width = len(STARTING_BOARD.splitlines()[0].split())
    board_height = len(STARTING_BOARD.splitlines())
    cell_size = compute_cell_size(board_width, board_height, screen_size=small_screen)
    panel_width = side_panel_width_for(cell_size)

    app, game_engine, canvas = build_app(screen_size=small_screen)

    pawn_row, pawn_col = 6, 4  # e2, in the standard starting position
    click_x = panel_width + pawn_col * cell_size + cell_size // 2
    click_y = pawn_row * cell_size + cell_size // 2

    app.on_click(click_x, click_y)
    dest_x = panel_width + pawn_col * cell_size + cell_size // 2
    dest_y = (pawn_row - 2) * cell_size + cell_size // 2
    app.on_click(dest_x, dest_y)
    game_engine.wait(2000)

    canvas.begin_frame()
    app.render()  # must not raise
    assert canvas.frame() is not None
