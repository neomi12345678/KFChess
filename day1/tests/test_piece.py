import pytest

from piece import EMPTY, make, color, kind, is_empty, other_color, is_king, all_piece_names, PIECE_TYPES, PIECE_COLORS


def test_make_and_properties():
    piece = make('w', 'Q')
    assert piece == 'wQ'
    assert color(piece) == 'w'
    assert kind(piece) == 'Q'
    assert not is_empty(piece)


def test_is_empty():
    assert is_empty(EMPTY)
    assert not is_empty('wP')


def test_other_color():
    assert other_color('w') == 'b'
    assert other_color('b') == 'w'


def test_is_king():
    assert is_king('wK')
    assert is_king('bK')
    assert not is_king('wQ')
    assert not is_king('bP')
    assert not is_king(EMPTY)


def test_all_piece_names():
    names = all_piece_names()
    assert len(names) == 12
    for c in PIECE_COLORS:
        for t in PIECE_TYPES:
            assert make(c, t) in names
