import pytest

from piece import EMPTY, make, color, kind, is_empty


def test_make_and_properties():
    piece = make('w', 'Q')
    assert piece == 'wQ'
    assert color(piece) == 'w'
    assert kind(piece) == 'Q'
    assert not is_empty(piece)


def test_is_empty():
    assert is_empty(EMPTY)
    assert not is_empty('wP')
