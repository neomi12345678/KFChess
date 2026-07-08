import pytest

from rules.arrival_rules import on_arrival, pawn_promotion
from piece import make


def test_on_arrival_non_pawn_stays_unchanged():
    assert on_arrival('wK', 0, 2) == 'wK'
    assert on_arrival('bR', 5, 8) == 'bR'


def test_pawn_promotion_on_arrival():
    assert on_arrival('wP', 0, 2) == 'wQ'
    assert on_arrival('bP', 1, 2) == 'bQ'
    assert on_arrival('wP', 1, 2) == 'wP'


def test_pawn_no_promotion_mid_board():
    assert on_arrival('wP', 3, 8) == 'wP'
    assert on_arrival('bP', 4, 8) == 'bP'


def test_pawn_promotion_asserts_for_non_pawn():
    with pytest.raises(AssertionError):
        pawn_promotion(make('w', 'K'), 0, 2)
