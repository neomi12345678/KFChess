from input.board_mapper import BoardMapper
from model.position import Position


def test_pixel_to_cell_maps_first_column():
    mapper = BoardMapper(width=3, height=3)

    assert mapper.pixel_to_cell(0, 50) == Position(0, 0)
    assert mapper.pixel_to_cell(99, 50) == Position(0, 0)


def test_pixel_to_cell_maps_second_column():
    mapper = BoardMapper(width=3, height=3)

    assert mapper.pixel_to_cell(100, 50) == Position(0, 1)
    assert mapper.pixel_to_cell(199, 50) == Position(0, 1)


def test_pixel_to_cell_maps_second_row():
    mapper = BoardMapper(width=3, height=3)

    assert mapper.pixel_to_cell(50, 100) == Position(1, 0)
    assert mapper.pixel_to_cell(50, 199) == Position(1, 0)


def test_pixel_to_cell_rejects_negative_coordinates():
    mapper = BoardMapper(width=3, height=3)

    assert mapper.pixel_to_cell(-1, 50) is None
    assert mapper.pixel_to_cell(50, -1) is None


def test_pixel_to_cell_rejects_coordinates_outside_the_board():
    mapper = BoardMapper(width=3, height=3)

    assert mapper.pixel_to_cell(300, 50) is None
    assert mapper.pixel_to_cell(50, 300) is None


def test_pixel_to_cell_uses_an_injected_cell_size_instead_of_the_configured_default():
    mapper = BoardMapper(width=3, height=3, cell_size=10)

    assert mapper.pixel_to_cell(15, 25) == Position(2, 1)


def test_board_offset_x_defaults_to_zero_and_behaves_like_before_side_panels_existed():
    mapper = BoardMapper(width=3, height=3)

    assert mapper.pixel_to_cell(0, 50) == Position(0, 0)


def test_board_offset_x_shifts_the_first_column_to_start_after_the_left_panel():
    # A side-panel window (see graphics/img_canvas.py's own board_offset_x)
    # draws the actual board starting board_offset_x pixels in - a click at
    # raw x=0 now lands in the panel, not on the board's first column.
    mapper = BoardMapper(width=3, height=3, board_offset_x=260)

    assert mapper.pixel_to_cell(0, 50) is None
    assert mapper.pixel_to_cell(260, 50) == Position(0, 0)
    assert mapper.pixel_to_cell(260 + 99, 50) == Position(0, 0)
    assert mapper.pixel_to_cell(260 + 100, 50) == Position(0, 1)
