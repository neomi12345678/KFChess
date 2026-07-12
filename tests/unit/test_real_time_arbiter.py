from boardio.board_parser import parse
from model.piece import AIRBORNE, CAPTURED, IDLE, MOVING
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter


def test_has_active_motion_false_when_nothing_moving():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)

    assert arbiter.has_active_motion() is False


def test_start_motion_marks_the_piece_as_moving_and_activates_arbiter():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))

    arbiter.start_motion(piece, Position(1, 1), Position(0, 1))

    assert arbiter.has_active_motion() is True
    assert piece.state == MOVING


def test_piece_has_not_arrived_after_999ms_for_a_one_cell_move():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_motion(piece, Position(1, 1), Position(0, 1))

    events = arbiter.advance_time(999)

    assert events == []
    assert board.get_piece(Position(1, 1)) is piece
    assert board.get_piece(Position(0, 1)) is None


def test_piece_arrives_after_1000ms_for_a_one_cell_move():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_motion(piece, Position(1, 1), Position(0, 1))

    events = arbiter.advance_time(1000)

    assert len(events) == 1
    assert board.get_piece(Position(1, 1)) is None
    assert board.get_piece(Position(0, 1)) is piece
    assert piece.state == IDLE
    assert arbiter.has_active_motion() is False


def test_partial_wait_followed_by_remaining_wait_equals_one_full_wait():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_motion(piece, Position(1, 1), Position(0, 1))

    arbiter.advance_time(400)
    events = arbiter.advance_time(600)

    assert len(events) == 1
    assert board.get_piece(Position(0, 1)) is piece


def test_multiple_waits_accumulate_correctly_for_a_two_cell_move():
    board = parse(". wR .\n. . .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(0, 1))
    arbiter.start_motion(piece, Position(0, 1), Position(2, 1))

    events_after_first_wait = arbiter.advance_time(1000)
    assert events_after_first_wait == []
    assert board.get_piece(Position(0, 1)) is piece

    events_after_second_wait = arbiter.advance_time(1000)
    assert len(events_after_second_wait) == 1
    assert board.get_piece(Position(2, 1)) is piece


def test_has_route_conflict_is_false_for_non_overlapping_paths():
    board = parse("wR . .\n. . .\nbR . .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(0, 0))
    arbiter.start_motion(rook, Position(0, 0), Position(0, 2))

    assert arbiter.has_route_conflict(Position(2, 0), Position(2, 2)) is False


def test_has_route_conflict_is_true_when_paths_share_a_cell():
    board = parse("wR . . bR")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(0, 0))
    arbiter.start_motion(rook, Position(0, 0), Position(0, 3))

    assert arbiter.has_route_conflict(Position(0, 3), Position(0, 0)) is True


def test_two_pieces_can_move_at_once_on_non_overlapping_routes():
    board = parse("wR . .\n. . .\nbR . .")
    arbiter = RealTimeArbiter(board)
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(2, 0))

    arbiter.start_motion(white_rook, Position(0, 0), Position(0, 2))
    arbiter.start_motion(black_rook, Position(2, 0), Position(2, 2))

    assert len(arbiter.get_active_motions()) == 2

    events = arbiter.advance_time(2000)

    assert len(events) == 2
    assert board.get_piece(Position(0, 2)) is white_rook
    assert board.get_piece(Position(2, 2)) is black_rook


def test_capturing_a_piece_removes_it_and_marks_it_captured():
    board = parse(". bP .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(1, 1))
    captured_pawn = board.get_piece(Position(0, 1))

    arbiter.start_motion(rook, Position(1, 1), Position(0, 1))
    events = arbiter.advance_time(1000)

    assert board.get_piece(Position(0, 1)) is rook
    assert captured_pawn.state == CAPTURED
    assert events[0].captured_piece is captured_pawn


def test_white_pawn_promotes_to_queen_on_arrival_at_row_zero():
    board = parse(". . .\n. wP .")
    arbiter = RealTimeArbiter(board)
    pawn = board.get_piece(Position(1, 1))

    arbiter.start_motion(pawn, Position(1, 1), Position(0, 1))
    arbiter.advance_time(1000)

    assert board.get_piece(Position(0, 1)).kind == "Q"


def test_black_pawn_promotes_to_queen_on_arrival_at_last_row():
    board = parse(". bP .\n. . .")
    arbiter = RealTimeArbiter(board)
    pawn = board.get_piece(Position(0, 1))

    arbiter.start_motion(pawn, Position(0, 1), Position(1, 1))
    arbiter.advance_time(1000)

    assert board.get_piece(Position(1, 1)).kind == "Q"


def test_pawn_does_not_promote_before_reaching_the_last_row():
    board = parse(". . .\n. . .\n. wP .\n. . .")
    arbiter = RealTimeArbiter(board)
    pawn = board.get_piece(Position(2, 1))

    arbiter.start_motion(pawn, Position(2, 1), Position(1, 1))
    arbiter.advance_time(1000)

    assert board.get_piece(Position(1, 1)).kind == "P"


def test_start_jump_marks_the_piece_airborne():
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 1))

    accepted = arbiter.start_jump(king)

    assert accepted is True
    assert king.state == AIRBORNE


def test_start_jump_rejects_a_piece_that_is_currently_moving():
    board = parse("wR . .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(0, 0))
    arbiter.start_motion(rook, Position(0, 0), Position(0, 2))

    accepted = arbiter.start_jump(rook)

    assert accepted is False
    assert rook.state == MOVING


def test_start_jump_rejects_a_piece_that_is_already_airborne():
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 1))
    arbiter.start_jump(king)

    accepted_again = arbiter.start_jump(king)

    assert accepted_again is False


def test_two_pieces_can_be_airborne_at_the_same_time():
    board = parse("wK . bK")
    arbiter = RealTimeArbiter(board)
    white_king = board.get_piece(Position(0, 0))
    black_king = board.get_piece(Position(0, 2))

    white_accepted = arbiter.start_jump(white_king)
    black_accepted = arbiter.start_jump(black_king)

    assert white_accepted is True
    assert black_accepted is True
    airborne_pieces = arbiter.get_airborne_pieces()
    assert white_king in airborne_pieces
    assert black_king in airborne_pieces
    assert len(airborne_pieces) == 2
    assert white_king.state == AIRBORNE
    assert black_king.state == AIRBORNE


def test_each_airborne_piece_lands_independently_when_its_own_duration_elapses():
    board = parse("wK . bK")
    arbiter = RealTimeArbiter(board)
    white_king = board.get_piece(Position(0, 0))
    black_king = board.get_piece(Position(0, 2))
    arbiter.start_jump(white_king)

    arbiter.advance_time(600)
    arbiter.start_jump(black_king)
    arbiter.advance_time(400)

    assert white_king.state == IDLE
    assert black_king.state == AIRBORNE
    assert arbiter.get_airborne_pieces() == [black_king]


def test_one_airborne_pieces_defense_does_not_affect_another_airborne_piece():
    board = parse("wK . bR\n. . .\nbK . .")
    arbiter = RealTimeArbiter(board)
    white_king = board.get_piece(Position(0, 0))
    black_king = board.get_piece(Position(2, 0))
    rook = board.get_piece(Position(0, 2))
    arbiter.start_jump(white_king)
    arbiter.start_jump(black_king)

    arbiter.start_motion(rook, Position(0, 2), Position(0, 0))
    arbiter.advance_time(2000)

    assert board.get_piece(Position(0, 0)) is white_king
    assert rook.state == CAPTURED
    assert black_king.state == IDLE
    assert arbiter.get_airborne_pieces() == []


def test_airborne_piece_lands_back_in_place_once_its_duration_elapses():
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 1))
    arbiter.start_jump(king)

    arbiter.advance_time(1000)

    assert king.state == IDLE
    assert board.get_piece(Position(1, 1)) is king


def test_airborne_piece_captures_an_enemy_that_arrives_on_its_cell():
    board = parse(". . .\nwK bR .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 0))
    rook = board.get_piece(Position(1, 1))
    arbiter.start_jump(king)

    arbiter.start_motion(rook, Position(1, 1), Position(1, 0))
    events = arbiter.advance_time(1000)

    assert board.get_piece(Position(1, 0)) is king
    assert board.get_piece(Position(1, 1)) is None
    assert rook.state == CAPTURED
    assert king.state == IDLE
    assert events[0].captured_piece is rook


def test_airborne_protection_no_longer_applies_once_it_has_expired():
    board = parse(". . . .\nwK . . bR\n. . . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 0))
    rook = board.get_piece(Position(1, 3))
    arbiter.start_jump(king)
    arbiter.advance_time(1000)

    arbiter.start_motion(rook, Position(1, 3), Position(1, 0))
    events = arbiter.advance_time(3000)

    assert board.get_piece(Position(1, 0)) is rook
    assert king.state == CAPTURED
    assert events[0].captured_piece is king
