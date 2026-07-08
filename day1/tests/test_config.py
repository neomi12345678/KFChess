from config import CELL_SIZE, MOVE_TIME_PER_CELL


def test_cell_size():
    assert CELL_SIZE == 100


def test_move_time_per_cell():
    assert MOVE_TIME_PER_CELL == 1000
