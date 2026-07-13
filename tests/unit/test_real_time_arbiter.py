from boardio.board_parser import parse
from model.piece import AIRBORNE, CAPTURED, IDLE, MOVING, PAWN, QUEEN
from model.position import Position
from realtime.real_time_arbiter import ArrivalEvent, RealTimeArbiter


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


def test_start_motion_rejects_a_piece_that_is_already_moving():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_motion(piece, Position(1, 1), Position(0, 1))

    accepted = arbiter.start_motion(piece, Position(1, 1), Position(1, 0))

    assert accepted is False
    assert len(arbiter.get_active_motions()) == 1


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
    other_rook = board.get_piece(Position(2, 0))
    arbiter.start_motion(rook, Position(0, 0), Position(0, 2))

    assert arbiter.has_route_conflict(other_rook, Position(2, 0), Position(2, 2)) is False


def test_has_route_conflict_is_true_when_paths_share_a_cell():
    board = parse("wR . . bR")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(0, 0))
    other_rook = board.get_piece(Position(0, 3))
    arbiter.start_motion(rook, Position(0, 0), Position(0, 3))

    assert arbiter.has_route_conflict(other_rook, Position(0, 3), Position(0, 0)) is True


def test_has_route_conflict_is_false_for_paths_that_cross_the_same_cell_at_different_times():
    board = parse(". . wR . .\nbR . . . .\n. . . . .\n. . . . .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(0, 2))
    other_rook = board.get_piece(Position(1, 0))
    arbiter.start_motion(rook, Position(0, 2), Position(2, 2))
    arbiter.advance_time(1900)

    # The vertical motion is almost done and long past (1, 2); a fresh
    # horizontal move through (1, 2) wouldn't arrive there for a while - no
    # real collision, even though the two paths share that grid cell.
    assert arbiter.has_route_conflict(other_rook, Position(1, 0), Position(1, 4)) is False


def test_has_route_conflict_is_false_for_a_knight_shaped_move_even_when_its_endpoint_crosses_another_path():
    board = parse("wR . .\n. . .\n. wN .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(0, 0))
    knight = board.get_piece(Position(2, 1))
    arbiter.start_motion(rook, Position(0, 0), Position(0, 2))

    # (2, 1) -> (0, 0) is an L-shape, not a straight line, so it's exempt
    # from route-conflict checking even though its endpoint (0, 0) lies on
    # the rook's active path.
    assert arbiter.has_route_conflict(knight, Position(2, 1), Position(0, 0)) is False


def test_route_planning_ignores_an_active_knight_shaped_motion_as_a_potential_blocker():
    board = parse("wN . .\n. . .\nbR . .")
    arbiter = RealTimeArbiter(board)
    knight = board.get_piece(Position(0, 0))
    rook = board.get_piece(Position(2, 0))
    arbiter.start_motion(knight, Position(0, 0), Position(1, 2))

    # A knight's in-flight motion has no continuous path to collide along,
    # so it must never be treated as a blocker for someone else's straight
    # move, even one that ends where the knight started.
    assert arbiter.has_route_conflict(rook, Position(2, 0), Position(0, 0)) is False


def test_a_knight_that_arrives_to_find_a_teammate_already_there_stays_at_its_source_cell():
    board = parse("wN . .\n. . wR")
    arbiter = RealTimeArbiter(board)
    knight = board.get_piece(Position(0, 0))
    rook = board.get_piece(Position(1, 2))
    arbiter.start_motion(knight, Position(0, 0), Position(1, 2))

    events = arbiter.advance_time(2000)

    # A knight has no partial path to fall back onto - retreat_cell treats
    # its own source as the "one cell short" landing spot.
    assert board.get_piece(Position(0, 0)) is knight
    assert knight.state == IDLE
    assert board.get_piece(Position(1, 2)) is rook
    assert events == [ArrivalEvent(piece=knight, captured_piece=None)]


def test_start_motion_is_rejected_when_it_would_cross_an_active_opposing_motion():
    board = parse("wR . . bR")
    arbiter = RealTimeArbiter(board)
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(0, 3))

    arbiter.start_motion(white_rook, Position(0, 0), Position(0, 3))
    # Whoever is already moving has right of way - black's head-on attempt
    # is rejected outright, not truncated into a mid-flight capture.
    accepted = arbiter.start_motion(black_rook, Position(0, 3), Position(0, 0))
    assert accepted is False
    assert black_rook.state == IDLE

    events = arbiter.advance_time(3000)

    # White's motion is entirely unaffected by the rejected request, and
    # captures black normally on arrival - black never left its square.
    assert board.get_piece(Position(0, 3)) is white_rook
    assert board.get_piece(Position(0, 0)) is None
    assert black_rook.state == CAPTURED
    assert events == [ArrivalEvent(piece=white_rook, captured_piece=black_rook)]
    assert arbiter.has_active_motion() is False


def test_start_motion_stops_a_same_color_piece_one_cell_short_of_a_crossing_path():
    board = parse(". . wR . .\n. . . . .\nwR . . . .\n. . . . .\n. . . . .")
    arbiter = RealTimeArbiter(board)
    vertical_rook = board.get_piece(Position(0, 2))
    horizontal_rook = board.get_piece(Position(2, 0))

    arbiter.start_motion(vertical_rook, Position(0, 2), Position(4, 2))
    # Both would reach (2, 2) at exactly 2000ms - same color, so the newly
    # commanded rook stops one cell short instead of sharing that cell.
    arbiter.start_motion(horizontal_rook, Position(2, 0), Position(2, 4))

    events = arbiter.advance_time(1000)

    assert board.get_piece(Position(2, 1)) is horizontal_rook
    assert horizontal_rook.state == IDLE
    assert events == [ArrivalEvent(piece=horizontal_rook, captured_piece=None)]
    # The already-active vertical motion is untouched by the other piece's
    # new command and keeps travelling toward its original destination.
    assert vertical_rook.state == MOVING
    assert arbiter.has_active_motion() is True


def test_start_motion_rejects_a_same_color_move_with_no_safe_cell_to_reach():
    board = parse("wR . . . wR")
    arbiter = RealTimeArbiter(board)
    first_rook = board.get_piece(Position(0, 0))
    second_rook = board.get_piece(Position(0, 4))

    arbiter.start_motion(first_rook, Position(0, 0), Position(0, 3))
    arbiter.advance_time(2000)

    # first_rook has 1 cell left and they'd meet exactly 1000ms into
    # second_rook's travel - no cell short of that to stop at safely.
    accepted = arbiter.start_motion(second_rook, Position(0, 4), Position(0, 1))

    assert accepted is False
    assert second_rook.state == IDLE
    assert len(arbiter.get_active_motions()) == 1


def test_start_motion_rejects_a_move_that_would_collide_with_an_enemy_before_reaching_one_cell():
    board = parse("wR . . . bR")
    arbiter = RealTimeArbiter(board)
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(0, 4))
    arbiter.start_motion(black_rook, Position(0, 4), Position(0, 0))
    arbiter.advance_time(3900)

    # Black is almost home, closing to a collision with white's requested
    # path only 50ms in - even this near-miss is rejected outright, same
    # as any other different-color route conflict.
    accepted = arbiter.start_motion(white_rook, Position(0, 0), Position(0, 4))

    assert accepted is False
    assert white_rook.state == IDLE
    assert board.get_piece(Position(0, 0)) is white_rook
    assert len(arbiter.get_active_motions()) == 1


def test_arrival_stops_short_instead_of_capturing_a_teammate_that_won_a_race_to_the_cell():
    board = parse(". . wR\n. . .\nwR . .")
    arbiter = RealTimeArbiter(board)
    from_the_left = board.get_piece(Position(2, 0))
    from_above = board.get_piece(Position(0, 2))

    # Both head for (2, 2) along paths that only ever share that one cell,
    # arriving at different times - plan_route never flags a conflict.
    arbiter.start_motion(from_the_left, Position(2, 0), Position(2, 2))
    arbiter.advance_time(500)
    accepted = arbiter.start_motion(from_above, Position(0, 2), Position(2, 2))
    assert accepted is True

    events = arbiter.advance_time(2500)

    assert board.get_piece(Position(2, 2)) is from_the_left
    assert from_the_left.state == IDLE
    # from_above loses the race and stops one cell short instead of
    # overwriting its teammate.
    assert board.get_piece(Position(1, 2)) is from_above
    assert from_above.state == IDLE
    assert ArrivalEvent(piece=from_above, captured_piece=None) in events


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

    assert board.get_piece(Position(0, 1)).kind == QUEEN


def test_black_pawn_promotes_to_queen_on_arrival_at_last_row():
    board = parse(". bP .\n. . .")
    arbiter = RealTimeArbiter(board)
    pawn = board.get_piece(Position(0, 1))

    arbiter.start_motion(pawn, Position(0, 1), Position(1, 1))
    arbiter.advance_time(1000)

    assert board.get_piece(Position(1, 1)).kind == QUEEN


def test_pawn_does_not_promote_before_reaching_the_last_row():
    board = parse(". . .\n. . .\n. wP .\n. . .")
    arbiter = RealTimeArbiter(board)
    pawn = board.get_piece(Position(2, 1))

    arbiter.start_motion(pawn, Position(2, 1), Position(1, 1))
    arbiter.advance_time(1000)

    assert board.get_piece(Position(1, 1)).kind == PAWN


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


def test_start_motion_succeeds_immediately_after_finishing_a_motion_without_cooldown():
    # Only jumping incurs a cooldown - an ordinary motion's arrival leaves
    # the piece immediately ready to move again.
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(1, 1))
    arbiter.start_motion(rook, Position(1, 1), Position(0, 1))
    arbiter.advance_time(1000)

    assert arbiter.is_in_cooldown(rook) is False
    accepted = arbiter.start_motion(rook, Position(0, 1), Position(0, 0))

    assert accepted is True


def test_start_jump_rejects_a_piece_still_in_cooldown_right_after_its_jump_expires():
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 1))
    arbiter.start_jump(king)
    arbiter.advance_time(1000)

    assert arbiter.is_in_cooldown(king) is True
    accepted = arbiter.start_jump(king)

    assert accepted is False
    assert king.state == IDLE


def test_start_jump_succeeds_again_once_the_cooldown_from_a_previous_jump_expires():
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 1))
    arbiter.start_jump(king)
    arbiter.advance_time(1000)

    arbiter.advance_time(1000)

    assert arbiter.is_in_cooldown(king) is False
    accepted = arbiter.start_jump(king)

    assert accepted is True


def test_cooldown_does_not_block_a_different_piece_from_acting():
    board = parse("wK . .\n. . .\nbR . .")
    arbiter = RealTimeArbiter(board)
    white_king = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(2, 0))
    arbiter.start_jump(white_king)
    arbiter.advance_time(1000)

    assert arbiter.is_in_cooldown(white_king) is True
    accepted = arbiter.start_motion(black_rook, Position(2, 0), Position(2, 1))

    assert accepted is True
