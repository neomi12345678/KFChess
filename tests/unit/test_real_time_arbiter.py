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
