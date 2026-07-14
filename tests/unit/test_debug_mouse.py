import debug_mouse


def test_debug_mouse_uses_a_standard_8x8_board():
    assert debug_mouse.BOARD_WIDTH == 8
    assert debug_mouse.BOARD_HEIGHT == 8


def test_hover_and_click_colors_are_distinct():
    assert debug_mouse.HOVER_COLOR != debug_mouse.CLICK_COLOR
