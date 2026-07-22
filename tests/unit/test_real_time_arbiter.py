from boardio.board_parser import parse
from logic_config import (
    AIRBORNE_BASE_DURATION_MS,
    AIRBORNE_DURATION_MULTIPLIER,
    LONG_REST_BASE_DURATION_MS,
    MOVE_CELL_DURATION_MS,
    REST_DURATION_MULTIPLIER,
    SHORT_REST_BASE_DURATION_MS,
)
from model.game_state import ArrivalEvent
from model.piece import CAPTURED, IDLE, MOVING, PAWN, QUEEN, WHITE, ROOK, Piece
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter

CELL_DURATION_MS = MOVE_CELL_DURATION_MS
AIRBORNE_DURATION_MS = round(AIRBORNE_BASE_DURATION_MS * AIRBORNE_DURATION_MULTIPLIER)
SHORT_REST_DURATION_MS = round(SHORT_REST_BASE_DURATION_MS * REST_DURATION_MULTIPLIER)
LONG_REST_DURATION_MS = round(LONG_REST_BASE_DURATION_MS * REST_DURATION_MULTIPLIER)


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


def test_piece_has_not_arrived_just_before_a_one_cell_move_completes():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_motion(piece, Position(1, 1), Position(0, 1))

    events = arbiter.advance_time(CELL_DURATION_MS - 1)

    assert events == []
    assert board.get_piece(Position(1, 1)) is piece
    assert board.get_piece(Position(0, 1)) is None


def test_piece_arrives_and_enters_long_rest_for_a_one_cell_move():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_motion(piece, Position(1, 1), Position(0, 1))

    events = arbiter.advance_time(CELL_DURATION_MS)

    assert len(events) == 1
    assert board.get_piece(Position(1, 1)) is None
    assert board.get_piece(Position(0, 1)) is piece
    # An ordinary arrival goes into long_rest, not straight to idle - see
    # logic_config.py's LONG_REST_BASE_DURATION_MS. piece.state itself goes
    # straight back to IDLE (see model/piece.py) - only is_in_cooldown()'s
    # own out-of-band bookkeeping remembers the cooldown.
    assert piece.state == IDLE
    assert arbiter.is_in_cooldown(piece) is True
    assert arbiter.has_active_motion() is False


def test_piece_returns_to_idle_once_its_long_rest_expires():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_motion(piece, Position(1, 1), Position(0, 1))

    arbiter.advance_time(CELL_DURATION_MS)
    assert arbiter.is_in_cooldown(piece) is True

    arbiter.advance_time(LONG_REST_DURATION_MS)

    assert arbiter.is_in_cooldown(piece) is False
    assert piece.state == IDLE


def test_is_in_long_rest_is_true_and_is_in_short_rest_is_false_after_an_ordinary_move_arrival():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_motion(piece, Position(1, 1), Position(0, 1))

    arbiter.advance_time(CELL_DURATION_MS)

    assert arbiter.is_in_long_rest(piece) is True
    assert arbiter.is_in_short_rest(piece) is False


def test_unavailable_progress_is_none_for_a_piece_that_is_idle():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))

    assert arbiter.unavailable_progress(piece) is None


def test_unavailable_progress_reports_elapsed_and_duration_during_a_long_rest():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_motion(piece, Position(1, 1), Position(0, 1))
    arbiter.advance_time(CELL_DURATION_MS)

    arbiter.advance_time(100)

    assert arbiter.unavailable_progress(piece) == (100, LONG_REST_DURATION_MS)


def test_unavailable_progress_counts_from_the_jump_itself_while_still_airborne():
    # A jump's own airborne hangtime is reported too, not just the
    # short_rest that follows it - so a view-facing cooldown clock has
    # something to show from the instant the jump is thrown, not only once
    # short_rest actually starts (see RealTimeArbiter.unavailable_progress's
    # own docstring for why - airborne badly outlasts the jump animation).
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_jump(piece)

    arbiter.advance_time(50)

    assert arbiter.unavailable_progress(piece) == (50, AIRBORNE_DURATION_MS + SHORT_REST_DURATION_MS)


def test_unavailable_progress_keeps_counting_continuously_into_the_short_rest_that_follows_a_jump():
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_jump(piece)
    arbiter.advance_time(AIRBORNE_DURATION_MS)

    arbiter.advance_time(50)

    assert arbiter.unavailable_progress(piece) == (
        AIRBORNE_DURATION_MS + 50,
        AIRBORNE_DURATION_MS + SHORT_REST_DURATION_MS,
    )


def test_partial_wait_followed_by_remaining_wait_equals_one_full_wait():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(1, 1))
    arbiter.start_motion(piece, Position(1, 1), Position(0, 1))

    arbiter.advance_time(CELL_DURATION_MS // 2)
    events = arbiter.advance_time(CELL_DURATION_MS - CELL_DURATION_MS // 2)

    assert len(events) == 1
    assert board.get_piece(Position(0, 1)) is piece


def test_multiple_waits_accumulate_correctly_for_a_two_cell_move():
    board = parse(". wR .\n. . .\n. . .")
    arbiter = RealTimeArbiter(board)
    piece = board.get_piece(Position(0, 1))
    arbiter.start_motion(piece, Position(0, 1), Position(2, 1))

    events_after_first_wait = arbiter.advance_time(CELL_DURATION_MS)
    assert events_after_first_wait == []
    assert board.get_piece(Position(0, 1)) is piece

    events_after_second_wait = arbiter.advance_time(CELL_DURATION_MS)
    assert len(events_after_second_wait) == 1
    assert board.get_piece(Position(2, 1)) is piece


def test_plan_route_is_not_blocked_for_non_overlapping_paths():
    board = parse("wR . .\n. . .\nbR . .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(0, 0))
    other_rook = board.get_piece(Position(2, 0))
    arbiter.start_motion(rook, Position(0, 0), Position(0, 2))

    assert arbiter.plan_route(other_rook, Position(2, 0), Position(2, 2)).is_blocked is False


def test_plan_route_is_blocked_when_paths_share_a_cell():
    board = parse("wR . . bR")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(0, 0))
    other_rook = board.get_piece(Position(0, 3))
    arbiter.start_motion(rook, Position(0, 0), Position(0, 3))

    plan = arbiter.plan_route(other_rook, Position(0, 3), Position(0, 0))
    assert plan.is_blocked is True
    # Opposing color, not just any blocker - start_motion uses this to
    # decide who captures whom (see _capture_blocked_mover).
    assert plan.blocking_enemy is rook


def test_plan_route_blocked_by_a_same_color_piece_names_no_blocking_enemy():
    board = parse("wR . . . wR")
    arbiter = RealTimeArbiter(board)
    first_rook = board.get_piece(Position(0, 0))
    second_rook = board.get_piece(Position(0, 4))
    arbiter.start_motion(first_rook, Position(0, 0), Position(0, 3))
    arbiter.advance_time(2 * CELL_DURATION_MS)

    plan = arbiter.plan_route(second_rook, Position(0, 4), Position(0, 1))
    assert plan.is_blocked is True
    # Friendly congestion, not an enemy collision - nobody gets captured
    # over it.
    assert plan.blocking_enemy is None


def test_plan_route_is_not_blocked_for_paths_that_cross_the_same_cell_at_different_times():
    board = parse(". . wR . .\nbR . . . .\n. . . . .\n. . . . .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(0, 2))
    other_rook = board.get_piece(Position(1, 0))
    arbiter.start_motion(rook, Position(0, 2), Position(2, 2))
    # Almost done but not yet complete - if this landed on or past the
    # motion's full 2*CELL_DURATION_MS, it would already be resolved and
    # removed from active_motions, making the conflict check trivially pass
    # for the wrong reason.
    arbiter.advance_time(2 * CELL_DURATION_MS - 50)

    # The vertical motion is almost done and long past (1, 2); a fresh
    # horizontal move through (1, 2) wouldn't arrive there for a while - no
    # real collision, even though the two paths share that grid cell.
    assert arbiter.plan_route(other_rook, Position(1, 0), Position(1, 4)).is_blocked is False


def test_plan_route_is_not_blocked_for_a_knight_shaped_move_even_when_its_endpoint_crosses_another_path():
    board = parse("wR . .\n. . .\n. wN .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(0, 0))
    knight = board.get_piece(Position(2, 1))
    arbiter.start_motion(rook, Position(0, 0), Position(0, 2))

    # (2, 1) -> (0, 0) is an L-shape, not a straight line, so it's exempt
    # from route-conflict checking even though its endpoint (0, 0) lies on
    # the rook's active path.
    assert arbiter.plan_route(knight, Position(2, 1), Position(0, 0)).is_blocked is False


def test_route_planning_ignores_an_active_knight_shaped_motion_as_a_potential_blocker():
    board = parse("wN . .\n. . .\nbR . .")
    arbiter = RealTimeArbiter(board)
    knight = board.get_piece(Position(0, 0))
    rook = board.get_piece(Position(2, 0))
    arbiter.start_motion(knight, Position(0, 0), Position(1, 2))

    # A knight's in-flight motion has no continuous path to collide along,
    # so it must never be treated as a blocker for someone else's straight
    # move, even one that ends where the knight started.
    assert arbiter.plan_route(rook, Position(2, 0), Position(0, 0)).is_blocked is False


def test_a_knight_that_arrives_to_find_a_teammate_already_there_stays_at_its_source_cell():
    board = parse("wN . .\n. . wR")
    arbiter = RealTimeArbiter(board)
    knight = board.get_piece(Position(0, 0))
    rook = board.get_piece(Position(1, 2))
    arbiter.start_motion(knight, Position(0, 0), Position(1, 2))

    events = arbiter.advance_time(2 * CELL_DURATION_MS)

    # A knight has no partial path to fall back onto - retreat_cell treats
    # its own source as the "one cell short" landing spot. It still
    # completed a motion (even a zero-distance one), so it still earns a
    # long_rest like any other arrival.
    assert board.get_piece(Position(0, 0)) is knight
    assert arbiter.is_in_cooldown(knight) is True
    assert board.get_piece(Position(1, 2)) is rook
    assert events == [ArrivalEvent(piece=knight, captured_piece=None)]


def test_start_motion_is_rejected_when_it_would_cross_an_active_opposing_motion():
    board = parse("wR . . bR")
    arbiter = RealTimeArbiter(board)
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(0, 3))

    arbiter.start_motion(white_rook, Position(0, 0), Position(0, 3))
    # Whoever is already moving has right of way - black's head-on attempt
    # is rejected outright and black is captured on the spot for trying to
    # cross a path white already committed to first.
    accepted = arbiter.start_motion(black_rook, Position(0, 3), Position(0, 0))
    assert accepted is False
    assert black_rook.state == CAPTURED
    assert board.get_piece(Position(0, 3)) is None
    # White is captured on the spot, but has not itself landed anywhere -
    # its own untouched motion is still flying toward (0, 3).
    assert arbiter.take_pending_events() == [
        ArrivalEvent(piece=white_rook, captured_piece=black_rook, has_landed=False)
    ]

    events = arbiter.advance_time(3 * CELL_DURATION_MS)

    # White's motion is entirely unaffected by the rejected request and
    # lands on the now-empty cell black used to occupy - no second capture.
    assert board.get_piece(Position(0, 3)) is white_rook
    assert board.get_piece(Position(0, 0)) is None
    assert black_rook.state == CAPTURED
    assert events == [ArrivalEvent(piece=white_rook, captured_piece=None)]
    assert arbiter.has_active_motion() is False


def test_start_motion_stops_a_same_color_piece_one_cell_short_of_a_crossing_path():
    board = parse(". . wR . .\n. . . . .\nwR . . . .\n. . . . .\n. . . . .")
    arbiter = RealTimeArbiter(board)
    vertical_rook = board.get_piece(Position(0, 2))
    horizontal_rook = board.get_piece(Position(2, 0))

    arbiter.start_motion(vertical_rook, Position(0, 2), Position(4, 2))
    # Both would reach (2, 2) at exactly 2 * CELL_DURATION_MS - same color,
    # so the newly commanded rook stops one cell short instead of sharing
    # that cell, shortening its own motion to exactly 1 * CELL_DURATION_MS.
    arbiter.start_motion(horizontal_rook, Position(2, 0), Position(2, 4))

    events = arbiter.advance_time(CELL_DURATION_MS)

    assert board.get_piece(Position(2, 1)) is horizontal_rook
    # Stopping short of a teammate still counts as completing a motion.
    assert arbiter.is_in_cooldown(horizontal_rook) is True
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
    arbiter.advance_time(2 * CELL_DURATION_MS)

    # first_rook has 1 cell left and they'd meet exactly one cell into
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
    arbiter.advance_time(4 * CELL_DURATION_MS - 100)

    # Black is almost home, closing to a collision with white's requested
    # path almost immediately - even this near-miss is rejected outright,
    # same as any other different-color route conflict, and white is
    # captured on the spot for trying to cross black's already-active path.
    accepted = arbiter.start_motion(white_rook, Position(0, 0), Position(0, 4))

    assert accepted is False
    assert white_rook.state == CAPTURED
    assert board.get_piece(Position(0, 0)) is None
    assert arbiter.take_pending_events() == [
        ArrivalEvent(piece=black_rook, captured_piece=white_rook, has_landed=False)
    ]
    assert len(arbiter.get_active_motions()) == 1


def test_arrival_stops_short_instead_of_capturing_a_teammate_that_won_a_race_to_the_cell():
    board = parse(". . wR\n. . .\nwR . .")
    arbiter = RealTimeArbiter(board)
    from_the_left = board.get_piece(Position(2, 0))
    from_above = board.get_piece(Position(0, 2))

    # Both head for (2, 2) along paths that only ever share that one cell,
    # arriving at different times - plan_route never flags a conflict.
    arbiter.start_motion(from_the_left, Position(2, 0), Position(2, 2))
    arbiter.advance_time(CELL_DURATION_MS // 2)
    accepted = arbiter.start_motion(from_above, Position(0, 2), Position(2, 2))
    assert accepted is True

    events = arbiter.advance_time(3 * CELL_DURATION_MS)

    assert board.get_piece(Position(2, 2)) is from_the_left
    assert arbiter.is_in_cooldown(from_the_left) is True
    # from_above loses the race and stops one cell short instead of
    # overwriting its teammate - it still completed a motion.
    assert board.get_piece(Position(1, 2)) is from_above
    assert arbiter.is_in_cooldown(from_above) is True
    assert ArrivalEvent(piece=from_above, captured_piece=None) in events


def test_two_pieces_can_move_at_once_on_non_overlapping_routes():
    board = parse("wR . .\n. . .\nbR . .")
    arbiter = RealTimeArbiter(board)
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(2, 0))

    arbiter.start_motion(white_rook, Position(0, 0), Position(0, 2))
    arbiter.start_motion(black_rook, Position(2, 0), Position(2, 2))

    assert len(arbiter.get_active_motions()) == 2

    events = arbiter.advance_time(2 * CELL_DURATION_MS)

    assert len(events) == 2
    assert board.get_piece(Position(0, 2)) is white_rook
    assert board.get_piece(Position(2, 2)) is black_rook


def test_capturing_a_piece_removes_it_and_marks_it_captured():
    board = parse(". bP .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(1, 1))
    captured_pawn = board.get_piece(Position(0, 1))

    arbiter.start_motion(rook, Position(1, 1), Position(0, 1))
    events = arbiter.advance_time(CELL_DURATION_MS)

    assert board.get_piece(Position(0, 1)) is rook
    assert captured_pawn.state == CAPTURED
    assert events[0].captured_piece is captured_pawn


def test_a_piece_captured_while_resting_does_not_get_resurrected_when_its_stale_rest_timer_expires():
    # Resting gives no protection against capture, unlike AIRBORNE.
    board = parse(". . .\n. wR .\nbR . .")
    arbiter = RealTimeArbiter(board)
    white_rook = board.get_piece(Position(1, 1))
    black_rook = board.get_piece(Position(2, 0))

    arbiter.start_motion(white_rook, Position(1, 1), Position(1, 0))
    arbiter.advance_time(CELL_DURATION_MS)
    assert arbiter.is_in_cooldown(white_rook) is True

    arbiter.start_motion(black_rook, Position(2, 0), Position(1, 0))
    arbiter.advance_time(CELL_DURATION_MS)
    assert white_rook.state == CAPTURED

    # Advance well past white_rook's original long_rest duration.
    arbiter.advance_time(LONG_REST_DURATION_MS + CELL_DURATION_MS)

    assert white_rook.state == CAPTURED


def test_a_piece_captured_mid_flight_does_not_leave_a_stale_motion_that_resurrects_it():
    board = parse("wR . . . . . . .\n. . . . . . . .\n. . . . . . . .\nbR . . . . . . .")
    arbiter = RealTimeArbiter(board)
    slow_mover = board.get_piece(Position(0, 0))  # heading far away (7 cells)
    fast_attacker = board.get_piece(Position(3, 0))  # heading to slow_mover's source (3 cells)

    arbiter.start_motion(slow_mover, Position(0, 0), Position(0, 7))
    arbiter.start_motion(fast_attacker, Position(3, 0), Position(0, 0))

    # Small ticks, like a real frame loop - one big lump sum would let both
    # arrivals resolve in the same call and mask the bug.
    for _ in range(1000):
        arbiter.advance_time(10)
        if slow_mover.state == CAPTURED:
            break

    assert slow_mover.state == CAPTURED
    assert board.get_piece(Position(0, 0)) is fast_attacker

    # Advance well past when slow_mover's original (now-stale) motion
    # would have arrived at its intended destination.
    for _ in range(1000):
        arbiter.advance_time(10)

    assert slow_mover.state == CAPTURED
    assert board.get_piece(Position(0, 7)) is None
    assert board.get_piece(Position(0, 0)) is fast_attacker


def test_a_pieces_own_arrival_is_skipped_if_it_was_captured_earlier_in_the_same_tick():
    # Same-duration motions completing in one advance_time call: the
    # attacker (started first) resolves first and captures the victim,
    # so the victim's own stale Motion must be skipped, not double-resolved.
    board = parse("wR . . .\n. . . .\n. . . .\nbR . . .")
    arbiter = RealTimeArbiter(board)
    victim = board.get_piece(Position(0, 0))
    attacker = board.get_piece(Position(3, 0))

    arbiter.start_motion(attacker, Position(3, 0), Position(0, 0))  # started first
    arbiter.start_motion(victim, Position(0, 0), Position(0, 3))  # same 3-cell duration

    arbiter.advance_time(3 * CELL_DURATION_MS + 100)  # both complete in one call

    assert victim.state == CAPTURED
    assert board.get_piece(Position(0, 3)) is None
    assert board.get_piece(Position(0, 0)) is attacker


def test_a_faster_enemy_piece_lands_in_a_slower_motions_path_and_is_captured_without_stopping_the_interceptor():
    # White's motion (5 cells, 5*CELL_DURATION_MS) is still far from column 3
    # when black's much shorter motion (1 cell) lands there - request-time
    # plan_route sees no conflict (the two trajectories are never at (0,3)
    # at the same instant), so without a mid-flight recheck white would
    # sail straight through black's now-occupied square. White has right of
    # way (it was already flying through this cell before black ever
    # landed there - see route_planner.plan_route's own docstring): black is
    # captured on the spot, but white's own motion is left completely
    # untouched and keeps flying all the way to its own original
    # destination - it does not stop at the collision cell.
    board = parse("wR . . . . .\n. . . bR . .")
    arbiter = RealTimeArbiter(board)
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(1, 3))

    arbiter.start_motion(white_rook, Position(0, 0), Position(0, 5))
    arbiter.start_motion(black_rook, Position(1, 3), Position(0, 3))

    # A single coarse wait spanning both completions - both motions are
    # "complete" by CELL_DURATION_MS bookkeeping within this one call, so
    # this also exercises the chronological (not insertion-order) sort.
    events = arbiter.advance_time(5 * CELL_DURATION_MS + 100)

    assert black_rook.state == CAPTURED
    # Black is simply gone, not replaced by white mid-path.
    assert board.get_piece(Position(0, 3)) is None
    assert board.get_piece(Position(0, 5)) is white_rook
    assert board.get_piece(Position(0, 0)) is None
    assert arbiter.is_in_cooldown(white_rook) is True
    # White has not landed at the moment it captures black mid-flight...
    assert ArrivalEvent(piece=white_rook, captured_piece=black_rook, has_landed=False) in events
    # ...only later, when it genuinely arrives at (0, 5) - nothing there to
    # capture by then, since black already died earlier in this same tick.
    assert ArrivalEvent(piece=white_rook, captured_piece=None) in events


def test_an_intercepted_piece_captured_right_after_landing_does_not_leave_a_stale_rest_entry():
    # Same setup as the interception test above, but black_rook is captured
    # via _intercept_motion (mid-flight interception) rather than
    # _resolve_arrival's own direct-arrival capture branch - the same
    # "resting gives no protection against capture" invariant
    # (_clear_pending_rests) has to hold on both paths, not just the direct
    # one already covered by
    # test_a_piece_captured_while_resting_does_not_get_resurrected_when_its_stale_rest_timer_expires.
    board = parse("wR . . . . .\n. . . bR . .")
    arbiter = RealTimeArbiter(board)
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(1, 3))

    arbiter.start_motion(white_rook, Position(0, 0), Position(0, 5))
    arbiter.start_motion(black_rook, Position(1, 3), Position(0, 3))

    arbiter.advance_time(5 * CELL_DURATION_MS + 100)

    assert black_rook.state == CAPTURED
    # No public accessor reports individual rest entries (only
    # is_in_cooldown() for a live piece still on the board) - the whole
    # point of _clear_pending_rests is that a captured piece leaves no
    # trace here at all, so this has to look at the arbiter's own
    # bookkeeping directly.
    assert all(rest.piece is not black_rook for rest in arbiter._long_rests)
    assert all(rest.piece is not black_rook for rest in arbiter._short_rests)


def test_a_faster_enemy_piece_lands_in_a_slower_motions_path_in_a_small_tick_loop():
    # Same scenario as above, but driven by a real per-frame-sized loop
    # instead of one coarse wait - the realistic path for interactive play.
    board = parse("wR . . . . .\n. . . bR . .")
    arbiter = RealTimeArbiter(board)
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(1, 3))

    arbiter.start_motion(white_rook, Position(0, 0), Position(0, 5))
    arbiter.start_motion(black_rook, Position(1, 3), Position(0, 3))

    for _ in range(1000):
        arbiter.advance_time(10)
        if black_rook.state == CAPTURED:
            break

    # Captured mid-flight - white hasn't landed anywhere yet, still moving
    # toward its own original destination.
    assert black_rook.state == CAPTURED
    assert board.get_piece(Position(0, 3)) is None
    assert white_rook.state == MOVING

    for _ in range(1000):
        arbiter.advance_time(10)
        if white_rook.state != MOVING:
            break

    assert board.get_piece(Position(0, 5)) is white_rook
    assert arbiter.is_in_cooldown(white_rook) is True


def test_a_faster_same_color_piece_lands_in_a_slower_motions_path_and_stops_it_one_cell_short():
    board = parse("wR . . . . .\n. . . wR . .")
    arbiter = RealTimeArbiter(board)
    slow_rook = board.get_piece(Position(0, 0))
    fast_rook = board.get_piece(Position(1, 3))

    arbiter.start_motion(slow_rook, Position(0, 0), Position(0, 5))
    # A plain 1-cell vertical move to (0, 3) - not a route_planner conflict
    # at request time (the two trajectories are never at (0, 3) at the same
    # instant, same reasoning as the opposite-color repro above), but it
    # still lands squarely on the rook's remaining path.
    arbiter.start_motion(fast_rook, Position(1, 3), Position(0, 3))

    # Only far enough for fast_rook's own 1-cell move to complete. The
    # interception shortens slow_rook's destination to (0, 2) right here,
    # but doesn't teleport it there - it's still mid-flight, only 1 of its
    # own now-2-cell trip elapsed, so it keeps gliding at its own pace
    # instead of the sprite jumping straight to the fallback cell.
    events = arbiter.advance_time(CELL_DURATION_MS + 100)

    assert board.get_piece(Position(0, 3)) is fast_rook
    assert board.get_piece(Position(0, 0)) is slow_rook
    assert slow_rook.state == MOVING
    assert arbiter.is_in_cooldown(slow_rook) is False
    assert ArrivalEvent(piece=slow_rook, captured_piece=None) not in events

    # slow_rook's own flight time (now just 2 cells, shortened from 5) only
    # actually completes once its elapsed_ms genuinely gets there.
    events = arbiter.advance_time(CELL_DURATION_MS - 100)

    # Stopped one cell short instead of overwriting a teammate.
    assert board.get_piece(Position(0, 2)) is slow_rook
    assert slow_rook.state == IDLE
    assert arbiter.is_in_cooldown(slow_rook) is True
    assert ArrivalEvent(piece=slow_rook, captured_piece=None) in events


def test_two_motions_completing_in_the_same_tick_on_non_crossing_paths_do_not_intercept_each_other():
    board = parse("wR . . . . .\n. . . . . .\n. . . bR . .")
    arbiter = RealTimeArbiter(board)
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(2, 3))

    arbiter.start_motion(white_rook, Position(0, 0), Position(0, 2))
    arbiter.start_motion(black_rook, Position(2, 3), Position(2, 1))

    events = arbiter.advance_time(2 * CELL_DURATION_MS)

    assert board.get_piece(Position(0, 2)) is white_rook
    assert board.get_piece(Position(2, 1)) is black_rook
    assert white_rook.state == IDLE
    assert black_rook.state == IDLE
    assert len(events) == 2


def test_a_still_flying_target_intercepts_every_enemy_landing_on_its_remaining_path_once_it_actually_gets_there():
    # target (6 cells, 4002ms) is nowhere near completing this tick, and
    # keeps right of way over its entire remaining path for as long as it's
    # still flying - capturing one enemy along the way doesn't end target's
    # own motion, so a second enemy landing further down that same path is
    # caught too, not just whichever one happened to land first. But
    # neither dies the instant target's motion merely predicts reaching
    # their cell - each is only captured once target's own elapsed_ms
    # genuinely gets there, matching where its sprite has actually flown to.
    board = parse("wR . . . . . .\n. . . bR . . .\n. . . . . bR .")
    arbiter = RealTimeArbiter(board)
    target = board.get_piece(Position(0, 0))
    late_attacker = board.get_piece(Position(2, 5))
    early_attacker = board.get_piece(Position(1, 3))

    arbiter.start_motion(target, Position(0, 0), Position(0, 6))
    arbiter.start_motion(late_attacker, Position(2, 5), Position(0, 5))  # requested first, completes later
    arbiter.start_motion(early_attacker, Position(1, 3), Position(0, 3))  # requested second, completes first

    # Both attackers land within this tick - target predicts both future
    # collisions (it's still only 2 of its own 6 cells in), but hasn't
    # actually reached column 3 or column 5 yet, so neither is captured.
    arbiter.advance_time(2 * CELL_DURATION_MS + 100)

    assert early_attacker.state == IDLE
    assert late_attacker.state == IDLE
    assert board.get_piece(Position(0, 3)) is early_attacker
    assert board.get_piece(Position(0, 5)) is late_attacker
    assert target.state == MOVING

    # Now target's own flight actually reaches column 3 (cell index 3) and
    # column 5 (index 5) - both captures resolve, still without target
    # landing anywhere (it's still 1 cell short of its own destination).
    events = arbiter.advance_time(3 * CELL_DURATION_MS)

    assert early_attacker.state == CAPTURED
    assert late_attacker.state == CAPTURED
    assert board.get_piece(Position(0, 3)) is None
    assert board.get_piece(Position(0, 5)) is None
    assert board.get_piece(Position(0, 6)) is None
    assert target.state == MOVING

    capture_events = [event for event in events if event.piece is target]
    assert len(capture_events) == 2
    captured = {event.captured_piece.id for event in capture_events}
    assert captured == {early_attacker.id, late_attacker.id}
    assert all(event.has_landed is False for event in capture_events)

    # target eventually lands for real, with nothing left to capture there.
    events = arbiter.advance_time(CELL_DURATION_MS)
    assert board.get_piece(Position(0, 6)) is target
    assert arbiter.is_in_cooldown(target) is True
    assert ArrivalEvent(piece=target, captured_piece=None) in events


def test_an_intercepted_motions_own_fallback_cell_can_itself_domino_into_a_third_motion():
    # m1 (white, fast) lands at (0, 3), intercepting m2 (white, slow,
    # still crossing that cell) into a same-color truncation - m2's own
    # destination shortens to (0, 2) right here, but m2 keeps gliding at its
    # own pace instead of being teleported there: it's still mid-flight,
    # only 1 of its now-2-cell trip elapsed, so it only actually settles at
    # (0, 2) once its own elapsed_ms genuinely gets there. That fallback
    # cell (0, 2) is itself on the remaining path of m3 (black, also still
    # in flight, already heading there before m2 ever retreated onto it) -
    # a domino one step removed from the original trigger. (0, 2) also
    # happens to be m3's own requested destination, so this doesn't even
    # need the deferred-interception bookkeeping at all: m3's own ordinary
    # _resolve_arrival captures whatever's still standing there once its
    # own full travel time has actually elapsed, exactly like any other
    # plain capture-on-arrival.
    board = parse(
        "wR . . . . . .\n"
        ". . . wR . . .\n"
        ". . . . . . .\n"
        ". . . . . . .\n"
        ". . . . . . .\n"
        ". . bR . . . .\n"
    )
    arbiter = RealTimeArbiter(board)
    m2_slow_rook = board.get_piece(Position(0, 0))
    m1_fast_rook = board.get_piece(Position(1, 3))
    m3_black_rook = board.get_piece(Position(5, 2))

    arbiter.start_motion(m2_slow_rook, Position(0, 0), Position(0, 6))  # 6 cells
    arbiter.start_motion(m1_fast_rook, Position(1, 3), Position(0, 3))  # 1 cell
    arbiter.start_motion(m3_black_rook, Position(5, 2), Position(0, 2))  # 5 cells

    # Only far enough for m1's 1-cell move to complete this tick.
    events = arbiter.advance_time(CELL_DURATION_MS + 100)

    assert board.get_piece(Position(0, 3)) is m1_fast_rook
    # m2's destination just got shortened to (0, 2), but it hasn't arrived
    # there yet - still mid-flight from (0, 0), only 1 of its new 2-cell
    # trip elapsed.
    assert board.get_piece(Position(0, 0)) is m2_slow_rook
    assert m2_slow_rook.state == MOVING
    assert arbiter.is_in_cooldown(m2_slow_rook) is False
    assert ArrivalEvent(piece=m2_slow_rook, captured_piece=None) not in events
    assert board.get_piece(Position(5, 2)) is m3_black_rook
    assert m3_black_rook.state == MOVING

    # m2's own (now-shortened) flight completes here - it safely reaches its
    # fallback cell under its own steam; m3 is nowhere near there yet.
    events = arbiter.advance_time(CELL_DURATION_MS - 100)
    assert board.get_piece(Position(0, 2)) is m2_slow_rook
    assert m2_slow_rook.state == IDLE
    assert arbiter.is_in_cooldown(m2_slow_rook) is True
    assert ArrivalEvent(piece=m2_slow_rook, captured_piece=None) in events

    # m3's own motion (5 cells) only actually completes later - only then
    # does it capture m2, exactly like any other arrival.
    events = arbiter.advance_time(3 * CELL_DURATION_MS + 100)
    assert board.get_piece(Position(0, 2)) is m3_black_rook
    assert board.get_piece(Position(5, 2)) is None
    assert m2_slow_rook.state == CAPTURED
    assert arbiter.is_in_cooldown(m3_black_rook) is True
    assert ArrivalEvent(piece=m3_black_rook, captured_piece=m2_slow_rook) in events


def test_two_same_tick_tied_interceptions_of_the_same_target_both_capture():
    # attacker_a and attacker_b both land, in the same tick, on different
    # cells that each independently lie on target's remaining path, at the
    # exact same chronological instant (identical 1-cell travel time - a
    # true tie, not just "both within the same coarse wait()"). target no
    # longer stops after its first capture (see the still-flying-target
    # test above), so both are eventually captured regardless of which one
    # target is checked against first - request order only fixes the
    # deterministic scheduling sequence, not who survives, since nobody
    # does. Neither dies until target's own flight genuinely reaches their
    # cell, same as any other interception.
    board = parse("bR . . . . . . .\n. . wR . wR . . .\n")
    arbiter = RealTimeArbiter(board)
    target = board.get_piece(Position(0, 0))
    attacker_a = board.get_piece(Position(1, 2))
    attacker_b = board.get_piece(Position(1, 4))

    arbiter.start_motion(target, Position(0, 0), Position(0, 6))  # 6 cells
    arbiter.start_motion(attacker_a, Position(1, 2), Position(0, 2))  # 1 cell, requested first
    arbiter.start_motion(attacker_b, Position(1, 4), Position(0, 4))  # 1 cell, requested second

    arbiter.advance_time(CELL_DURATION_MS + 100)

    # Both landed, both collisions predicted - but target is still only 2
    # of its own 6 cells in, nowhere near column 2 or column 4 yet.
    assert attacker_a.state == IDLE
    assert attacker_b.state == IDLE
    assert target.state == MOVING

    events = arbiter.advance_time(3 * CELL_DURATION_MS)

    assert attacker_a.state == CAPTURED
    assert attacker_b.state == CAPTURED
    assert board.get_piece(Position(0, 2)) is None
    assert board.get_piece(Position(0, 4)) is None
    assert board.get_piece(Position(0, 6)) is None
    assert target.state == MOVING

    capture_events = [event for event in events if event.piece is target]
    assert len(capture_events) == 2
    captured = {event.captured_piece.id for event in capture_events}
    assert captured == {attacker_a.id, attacker_b.id}


def test_white_pawn_promotes_to_queen_on_arrival_at_row_zero():
    board = parse(". . .\n. wP .")
    arbiter = RealTimeArbiter(board)
    pawn = board.get_piece(Position(1, 1))

    arbiter.start_motion(pawn, Position(1, 1), Position(0, 1))
    arbiter.advance_time(CELL_DURATION_MS)

    assert board.get_piece(Position(0, 1)).kind == QUEEN


def test_black_pawn_promotes_to_queen_on_arrival_at_last_row():
    board = parse(". bP .\n. . .")
    arbiter = RealTimeArbiter(board)
    pawn = board.get_piece(Position(0, 1))

    arbiter.start_motion(pawn, Position(0, 1), Position(1, 1))
    arbiter.advance_time(CELL_DURATION_MS)

    assert board.get_piece(Position(1, 1)).kind == QUEEN


def test_pawn_does_not_promote_before_reaching_the_last_row():
    board = parse(". . .\n. . .\n. wP .\n. . .")
    arbiter = RealTimeArbiter(board)
    pawn = board.get_piece(Position(2, 1))

    arbiter.start_motion(pawn, Position(2, 1), Position(1, 1))
    arbiter.advance_time(CELL_DURATION_MS)

    assert board.get_piece(Position(1, 1)).kind == PAWN


def test_start_jump_marks_the_piece_airborne():
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 1))

    accepted = arbiter.start_jump(king)

    assert accepted is True
    assert arbiter.is_airborne(king) is True
    # piece.state stays IDLE for the whole jump - see model/piece.py.
    assert king.state == IDLE


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
    assert arbiter.is_airborne(white_king) is True
    assert arbiter.is_airborne(black_king) is True


def test_each_airborne_piece_lands_independently_when_its_own_duration_elapses():
    board = parse("wK . bK")
    arbiter = RealTimeArbiter(board)
    white_king = board.get_piece(Position(0, 0))
    black_king = board.get_piece(Position(0, 2))
    arbiter.start_jump(white_king)

    half = AIRBORNE_DURATION_MS // 2
    arbiter.advance_time(half)
    arbiter.start_jump(black_king)
    arbiter.advance_time(AIRBORNE_DURATION_MS - half)

    # White's jump has now run its full duration and landed into
    # short_rest; black's jump only just started and is still airborne.
    assert arbiter.is_airborne(white_king) is False
    assert arbiter.is_in_cooldown(white_king) is True
    assert arbiter.is_airborne(black_king) is True
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
    arbiter.advance_time(2 * CELL_DURATION_MS)

    assert board.get_piece(Position(0, 0)) is white_king
    assert rook.state == CAPTURED
    # black_king's own, unrelated jump is untouched by white_king's defense.
    assert arbiter.is_airborne(black_king) is True

    arbiter.advance_time(AIRBORNE_DURATION_MS - 2 * CELL_DURATION_MS)

    assert arbiter.is_airborne(black_king) is False
    assert arbiter.is_in_cooldown(black_king) is True
    assert arbiter.get_airborne_pieces() == []


def test_airborne_piece_lands_back_in_place_once_its_duration_elapses():
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 1))
    arbiter.start_jump(king)

    arbiter.advance_time(AIRBORNE_DURATION_MS)

    assert arbiter.is_airborne(king) is False
    assert arbiter.is_in_cooldown(king) is True
    assert board.get_piece(Position(1, 1)) is king


def test_airborne_piece_captures_an_enemy_that_arrives_on_its_cell():
    board = parse(". . .\nwK bR .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 0))
    rook = board.get_piece(Position(1, 1))
    arbiter.start_jump(king)

    arbiter.start_motion(rook, Position(1, 1), Position(1, 0))
    events = arbiter.advance_time(CELL_DURATION_MS)

    assert board.get_piece(Position(1, 0)) is king
    assert board.get_piece(Position(1, 1)) is None
    assert rook.state == CAPTURED
    # A successful defense goes straight back to idle - it doesn't tire the
    # defender the way completing a jump on its own does.
    assert king.state == IDLE
    assert events[0].captured_piece is rook


def test_airborne_piece_does_not_capture_a_teammate_that_arrives_on_its_cell():
    board = parse(". . .\nwK wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 0))
    rook = board.get_piece(Position(1, 1))

    # Rook starts first and is already halfway home before the king jumps,
    # so the king is still mid-jump (not yet expired) when the rook arrives.
    arbiter.start_motion(rook, Position(1, 1), Position(1, 0))
    arbiter.advance_time(CELL_DURATION_MS // 2)
    arbiter.start_jump(king)
    events = arbiter.advance_time(CELL_DURATION_MS - CELL_DURATION_MS // 2)

    assert board.get_piece(Position(1, 0)) is king
    assert board.get_piece(Position(1, 1)) is rook
    assert arbiter.is_in_cooldown(rook) is True
    assert arbiter.is_airborne(king) is True
    assert events == [ArrivalEvent(piece=rook, captured_piece=None)]


def test_airborne_protection_no_longer_applies_once_it_has_expired():
    board = parse(". . . .\nwK . . bR\n. . . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 0))
    rook = board.get_piece(Position(1, 3))
    arbiter.start_jump(king)
    arbiter.advance_time(AIRBORNE_DURATION_MS)
    assert arbiter.is_in_cooldown(king) is True

    arbiter.start_motion(rook, Position(1, 3), Position(1, 0))
    events = arbiter.advance_time(3 * CELL_DURATION_MS)

    assert board.get_piece(Position(1, 0)) is rook
    assert king.state == CAPTURED
    assert events[0].captured_piece is king


def test_start_motion_rejects_a_piece_still_in_long_rest_right_after_finishing_a_motion():
    # Every ordinary arrival earns a long_rest - the piece can't act again
    # until it expires.
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(1, 1))
    arbiter.start_motion(rook, Position(1, 1), Position(0, 1))
    arbiter.advance_time(CELL_DURATION_MS)

    assert arbiter.is_in_cooldown(rook) is True
    accepted = arbiter.start_motion(rook, Position(0, 1), Position(0, 0))

    assert accepted is False
    assert arbiter.is_in_cooldown(rook) is True


def test_start_motion_succeeds_again_once_the_long_rest_from_a_previous_move_expires():
    board = parse(". . .\n. wR .\n. . .")
    arbiter = RealTimeArbiter(board)
    rook = board.get_piece(Position(1, 1))
    arbiter.start_motion(rook, Position(1, 1), Position(0, 1))
    arbiter.advance_time(CELL_DURATION_MS)

    arbiter.advance_time(LONG_REST_DURATION_MS)

    assert arbiter.is_in_cooldown(rook) is False
    accepted = arbiter.start_motion(rook, Position(0, 1), Position(0, 0))

    assert accepted is True


def test_start_jump_rejects_a_piece_still_in_short_rest_right_after_its_jump_expires():
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 1))
    arbiter.start_jump(king)
    arbiter.advance_time(AIRBORNE_DURATION_MS)

    assert arbiter.is_in_cooldown(king) is True
    accepted = arbiter.start_jump(king)

    assert accepted is False
    assert arbiter.is_in_cooldown(king) is True


def test_start_jump_succeeds_again_once_the_short_rest_from_a_previous_jump_expires():
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 1))
    arbiter.start_jump(king)
    arbiter.advance_time(AIRBORNE_DURATION_MS)

    arbiter.advance_time(SHORT_REST_DURATION_MS)

    assert arbiter.is_in_cooldown(king) is False
    accepted = arbiter.start_jump(king)

    assert accepted is True


def test_is_in_short_rest_is_true_and_is_in_long_rest_is_false_after_a_jump_lands():
    board = parse(". . .\n. wK .\n. . .")
    arbiter = RealTimeArbiter(board)
    king = board.get_piece(Position(1, 1))
    arbiter.start_jump(king)

    arbiter.advance_time(AIRBORNE_DURATION_MS)

    assert arbiter.is_in_short_rest(king) is True
    assert arbiter.is_in_long_rest(king) is False


def test_cooldown_does_not_block_a_different_piece_from_acting():
    board = parse("wK . .\n. . .\nbR . .")
    arbiter = RealTimeArbiter(board)
    white_king = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(2, 0))
    arbiter.start_jump(white_king)
    arbiter.advance_time(AIRBORNE_DURATION_MS)

    assert arbiter.is_in_cooldown(white_king) is True
    accepted = arbiter.start_motion(black_rook, Position(2, 0), Position(2, 1))

    assert accepted is True
