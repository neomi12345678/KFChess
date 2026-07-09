from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.model.position import Position


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
