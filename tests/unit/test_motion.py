from model.position import Position
from realtime.motion import Trajectory, is_straight_line, motion_duration_ms, trajectories_collide


def test_is_straight_line_true_for_a_horizontal_move():
    assert is_straight_line(Position(0, 0), Position(0, 3)) is True


def test_is_straight_line_true_for_a_diagonal_move():
    assert is_straight_line(Position(0, 0), Position(3, 3)) is True


def test_is_straight_line_false_for_a_knight_shaped_move():
    assert is_straight_line(Position(2, 1), Position(0, 0)) is False


def test_motion_duration_ms_scales_with_distance():
    assert motion_duration_ms(Position(0, 0), Position(0, 3)) == 3000


def test_trajectories_collide_true_when_two_pieces_meet_head_on():
    a = Trajectory(Position(0, 0), Position(0, 3), duration_ms=3000)
    b = Trajectory(Position(0, 3), Position(0, 0), duration_ms=3000)

    assert trajectories_collide(a, b) is True


def test_trajectories_collide_false_for_parallel_non_crossing_paths():
    a = Trajectory(Position(0, 0), Position(0, 2), duration_ms=2000)
    b = Trajectory(Position(2, 0), Position(2, 2), duration_ms=2000)

    assert trajectories_collide(a, b) is False


def test_trajectories_collide_false_when_paths_cross_the_same_cell_at_different_times():
    # A vertical motion nearly done (started 1900ms ago, 2000ms total) passed
    # through (1, 2) long before "now" and is about to land. A fresh
    # horizontal request through the same cell (1, 2) wouldn't get there for
    # another 2000ms. The paths share a grid cell, but the two pieces are
    # never actually there together, so this must NOT count as a collision -
    # this is exactly the case the discrete cell-overlap check got wrong.
    in_flight = Trajectory(Position(0, 2), Position(2, 2), duration_ms=2000, start_offset_ms=-1900)
    requested = Trajectory(Position(1, 0), Position(1, 4), duration_ms=4000)

    assert trajectories_collide(in_flight, requested) is False


def test_trajectories_collide_true_when_paths_cross_the_same_cell_at_the_same_time():
    # Same crossing cell (1, 2) as above, but timed so both trajectories are
    # actually there at t=1000 - a genuine collision.
    a = Trajectory(Position(0, 2), Position(2, 2), duration_ms=2000)
    b = Trajectory(Position(1, 0), Position(1, 4), duration_ms=2000)

    assert trajectories_collide(a, b) is True


def test_trajectories_collide_true_for_two_pieces_closing_in_along_the_same_file():
    # Both move vertically in column 2 toward each other - same column rate
    # (0) and the same column throughout, so only the row equation decides
    # when they meet. This is the parallel-trajectory branch the head-on
    # test above doesn't reach (that one varies by column, not row).
    a = Trajectory(Position(0, 2), Position(4, 2), duration_ms=4000)
    b = Trajectory(Position(6, 2), Position(2, 2), duration_ms=4000)

    assert trajectories_collide(a, b) is True


def test_trajectories_collide_false_for_two_pieces_in_the_same_file_that_never_meet_in_time():
    # Same column-aligned setup as above, but they'd only meet after both
    # motions are long finished - the row equation has a solution, it just
    # falls outside either trajectory's time window.
    a = Trajectory(Position(0, 2), Position(1, 2), duration_ms=1000)
    b = Trajectory(Position(5, 2), Position(4, 2), duration_ms=1000)

    assert trajectories_collide(a, b) is False


def test_trajectories_collide_false_when_time_windows_dont_overlap_at_all():
    a = Trajectory(Position(0, 0), Position(0, 3), duration_ms=1000, start_offset_ms=-1000)
    b = Trajectory(Position(0, 3), Position(0, 0), duration_ms=1000, start_offset_ms=5000)

    assert trajectories_collide(a, b) is False


def test_trajectories_collide_false_when_one_trajectory_has_zero_duration():
    # A zero-duration trajectory (source and destination the same point) has
    # no rate to divide by - must be guarded explicitly rather than crashing.
    stationary = Trajectory(Position(0, 0), Position(0, 0), duration_ms=0)
    moving = Trajectory(Position(0, 0), Position(0, 3), duration_ms=3000)

    assert trajectories_collide(stationary, moving) is False


def test_trajectories_collide_true_when_both_trajectories_are_identical():
    # Same source, destination, and duration - the degenerate case where
    # every rate and offset matches, not just the ones that vary.
    a = Trajectory(Position(0, 0), Position(0, 3), duration_ms=3000)
    b = Trajectory(Position(0, 0), Position(0, 3), duration_ms=3000)

    assert trajectories_collide(a, b) is True
