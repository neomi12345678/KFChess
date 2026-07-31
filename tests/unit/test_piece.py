import dataclasses

from model.piece import (
    CAPTURED,
    IDLE,
    KING,
    MOVING,
    PAWN,
    PHASE_JUMP,
    MotionPhase,
    Piece,
    PieceKind,
    PieceState,
    WHITE,
)
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


# view/renderer.py builds a sprite-lookup key by interpolating piece.kind/
# piece.state/piece.motion_phase directly into an f-string, later split
# back apart in view/canvas/img_canvas.py - Python 3.11+ changed
# Enum.__format__ to render a mixed-in member as e.g. "PieceKind.KING" in
# an f-string instead of its plain value, which would silently corrupt
# that key (wrong field count/content) if PieceKind/PieceState/MotionPhase
# ever lost the explicit __str__ override each defines for exactly this
# reason (see model/piece.py's own comment on Color, which all three copy).
def test_piece_kind_state_and_phase_format_as_their_plain_value_in_an_fstring():
    assert f"{KING}" == "king"
    assert f"{IDLE}" == "idle"
    assert f"{PHASE_JUMP}" == "jump"


def test_piece_kind_state_and_phase_are_real_enum_members_of_their_own_class():
    assert isinstance(KING, PieceKind)
    assert isinstance(IDLE, PieceState)
    assert isinstance(PHASE_JUMP, MotionPhase)


# str-Enum backward compatibility - every existing `piece.kind == "king"`-
# style comparison, dict-key lookup, and json.dumps call site across the
# codebase depends on this holding, the same as it already does for Color.
def test_piece_kind_state_and_phase_still_compare_equal_to_their_plain_string():
    assert KING == "king"
    assert IDLE == "idle"
    assert PHASE_JUMP == "jump"
