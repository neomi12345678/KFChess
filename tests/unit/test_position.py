from model.position import Position


def test_position_stores_row_and_col():
    position = Position(row=2, col=3)

    assert position.row == 2
    assert position.col == 3


def test_position_equality_by_value():
    assert Position(1, 1) == Position(1, 1)
    assert Position(1, 1) != Position(1, 2)


def test_position_is_hashable():
    positions = {Position(0, 0), Position(0, 0), Position(1, 0)}

    assert positions == {Position(0, 0), Position(1, 0)}


def test_position_repr_is_readable():
    assert repr(Position(2, 3)) == "Position(row=2, col=3)"
