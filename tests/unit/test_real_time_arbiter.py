from kungfu_chess.io.board_parser import parse
from kungfu_chess.model.piece import CAPTURED, IDLE, MOVING
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter


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
