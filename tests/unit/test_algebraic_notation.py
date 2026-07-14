from boardio.algebraic_notation import jump_notation, move_notation, square_name
from model.piece import BISHOP, KNIGHT, PAWN, QUEEN
from model.position import Position


def test_square_name_maps_row_zero_to_the_last_rank():
    # Row 0 is black's back rank (see boardio/algebraic_notation.py's own
    # comment) - on a standard 8-tall board that's rank 8, file "a" at col 0.
    assert square_name(Position(0, 0), board_height=8) == "a8"


def test_square_name_maps_the_last_row_to_rank_one():
    assert square_name(Position(7, 7), board_height=8) == "h1"


def test_move_notation_for_a_plain_pawn_advance_has_no_letter_or_capture_marker():
    assert move_notation(PAWN, Position(6, 4), Position(4, 4), board_height=8, is_capture=False) == "e4"


def test_move_notation_for_a_pawn_capture_names_the_source_file():
    assert move_notation(PAWN, Position(3, 4), Position(2, 3), board_height=8, is_capture=True) == "exd6"


def test_move_notation_for_a_piece_move_uses_its_letter():
    assert move_notation(KNIGHT, Position(7, 1), Position(5, 2), board_height=8, is_capture=False) == "Nc3"


def test_move_notation_for_a_piece_capture_inserts_x():
    assert move_notation(BISHOP, Position(7, 5), Position(3, 1), board_height=8, is_capture=True) == "Bxb5"


def test_jump_notation_marks_the_pieces_own_square_with_a_caret():
    # Jump has no destination (it's in place) - see
    # realtime.real_time_arbiter.RealTimeArbiter.start_jump.
    assert jump_notation(QUEEN, Position(4, 4), board_height=8) == "Qe4^"


def test_jump_notation_for_a_pawn_has_no_letter():
    assert jump_notation(PAWN, Position(4, 4), board_height=8) == "e4^"
