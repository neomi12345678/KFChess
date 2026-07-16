from display_config import CELL_SIZE, SIDE_PANEL_WIDTH_PX, compute_cell_size, side_panel_width_for


def test_compute_cell_size_falls_back_to_the_fixed_default_when_the_screen_is_unknown():
    cell_size = compute_cell_size(8, 8, screen_size=lambda: (None, None))

    assert cell_size == CELL_SIZE


def test_compute_cell_size_shrinks_below_the_default_for_a_small_screen():
    cell_size = compute_cell_size(8, 8, screen_size=lambda: (1000, 700))

    assert cell_size < CELL_SIZE


def test_compute_cell_size_grows_above_the_default_for_a_large_screen():
    cell_size = compute_cell_size(8, 8, screen_size=lambda: (4000, 3000))

    assert cell_size > CELL_SIZE


def test_compute_cell_size_fits_the_board_and_both_panels_within_the_screen_height():
    board_width, board_height = 8, 8
    screen_width, screen_height = 1000, 700

    cell_size = compute_cell_size(board_width, board_height, screen_size=lambda: (screen_width, screen_height))

    assert board_height * cell_size <= screen_height


def test_compute_cell_size_fits_the_board_and_both_panels_within_the_screen_width():
    board_width, board_height = 8, 8
    screen_width, screen_height = 1000, 700

    cell_size = compute_cell_size(board_width, board_height, screen_size=lambda: (screen_width, screen_height))
    panel_width = side_panel_width_for(cell_size)

    assert board_width * cell_size + 2 * panel_width <= screen_width


def test_compute_cell_size_never_shrinks_below_the_readability_floor_on_a_tiny_screen():
    cell_size = compute_cell_size(8, 8, screen_size=lambda: (50, 50))

    assert cell_size >= 20


def test_side_panel_width_for_the_default_cell_size_matches_the_fixed_constant():
    assert side_panel_width_for(CELL_SIZE) == SIDE_PANEL_WIDTH_PX


def test_side_panel_width_for_scales_proportionally_with_cell_size():
    assert side_panel_width_for(CELL_SIZE // 2) == round(SIDE_PANEL_WIDTH_PX / 2)
