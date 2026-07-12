import dataclasses

from model.piece import CAPTURED, IDLE, MOVING, PAWN, Piece, WHITE
from model.position import Position


def test_piece_defaults_to_idle_state():
    piece = Piece(id="w-p-1", color=WHITE, kind=PAWN, cell=Position(0, 0))

    assert piece.state == IDLE


def test_piece_state_can_become_moving_or_captured():
    piece = Piece(id="w-p-1", color=WHITE, kind=PAWN, cell=Position(0, 0))

    piece.state = MOVING
    assert piece.state == MOVING

    piece.state = CAPTURED
    assert piece.state == CAPTURED


def test_piece_has_no_timing_or_destination_fields():
    field_names = {f.name for f in dataclasses.fields(Piece)}

    assert field_names == {"id", "color", "kind", "cell", "state"}
