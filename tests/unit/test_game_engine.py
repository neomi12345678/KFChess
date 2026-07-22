from dataclasses import FrozenInstanceError

import pytest

from engine.game_engine import GameEngine
from boardio.board_parser import parse
from events.observers import MoveLogObserver
from logic_config import (
    AIRBORNE_BASE_DURATION_MS,
    AIRBORNE_DURATION_MULTIPLIER,
    LONG_REST_BASE_DURATION_MS,
    MOVE_CELL_DURATION_MS,
    REST_DURATION_MULTIPLIER,
    SHORT_REST_BASE_DURATION_MS,
)
from model.game_state import ArrivalEvent, GameObserver, MoveLoggedEvent
from model.piece import (
    BLACK,
    CAPTURED,
    IDLE,
    KING,
    MOVING,
    PAWN,
    PHASE_IDLE,
    PHASE_JUMP,
    PHASE_LONG_REST,
    PHASE_MOVE,
    PHASE_SHORT_REST,
    ROOK,
    WHITE,
    Piece,
)
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine


class RecordingObserver(GameObserver):
    def __init__(self):
        self.logged_moves = []
        self.arrivals = []

    def on_move_logged(self, event: MoveLoggedEvent) -> None:
        self.logged_moves.append(event)

    def on_arrival(self, event: ArrivalEvent) -> None:
        self.arrivals.append(event)

CELL_DURATION_MS = MOVE_CELL_DURATION_MS
AIRBORNE_DURATION_MS = round(AIRBORNE_BASE_DURATION_MS * AIRBORNE_DURATION_MULTIPLIER)
LONG_REST_DURATION_MS = round(LONG_REST_BASE_DURATION_MS * REST_DURATION_MULTIPLIER)
SHORT_REST_DURATION_MS = round(SHORT_REST_BASE_DURATION_MS * REST_DURATION_MULTIPLIER)


def make_engine(board_text):
    board = parse(board_text)
    arbiter = RealTimeArbiter(board)
    engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=arbiter)
    return board, engine, arbiter


def test_request_move_accepts_a_legal_move_and_starts_a_motion():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")

    result = engine.request_move(Position(1, 1), Position(0, 1))

    assert result.is_accepted is True
    assert result.reason == "ok"
    assert arbiter.has_active_motion() is True


def test_request_move_rejects_an_illegal_move_with_the_rule_engine_reason():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")

    result = engine.request_move(Position(1, 1), Position(0, 0))

    assert result.is_accepted is False
    assert result.reason == "illegal_piece_move"
    assert arbiter.has_active_motion() is False


def test_request_move_checks_game_over_before_calling_rule_engine():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.game_over = True

    result = engine.request_move(Position(1, 1), Position(0, 1))

    assert result.is_accepted is False
    assert result.reason == "game_over"


def test_invalid_command_does_not_mutate_board_or_start_a_motion():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")

    engine.request_move(Position(1, 1), Position(0, 0))

    assert board.get_piece(Position(1, 1)) is not None
    assert board.get_piece(Position(0, 0)) is None
    assert arbiter.has_active_motion() is False


def test_request_move_rejects_a_second_move_while_a_motion_is_active():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))

    result = engine.request_move(Position(1, 1), Position(1, 0))

    assert result.is_accepted is False
    assert result.reason == "motion_in_progress"


def test_request_move_rejects_a_piece_that_is_currently_airborne():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    engine.request_jump(Position(1, 1))

    result = engine.request_move(Position(1, 1), Position(0, 1))

    assert result.is_accepted is False
    assert result.reason == "piece_is_airborne"
    assert arbiter.has_active_motion() is False


def test_request_move_allows_two_pieces_to_move_concurrently_on_non_overlapping_routes():
    board, engine, arbiter = make_engine("wR . .\n. . .\nbR . .")

    white_result = engine.request_move(Position(0, 0), Position(0, 2))
    black_result = engine.request_move(Position(2, 0), Position(2, 2))

    assert white_result.is_accepted is True
    assert black_result.is_accepted is True
    assert len(arbiter.get_active_motions()) == 2

    engine.wait(2000)

    assert board.get_piece(Position(0, 2)) is not None
    assert board.get_piece(Position(2, 2)) is not None


def test_request_move_is_rejected_when_it_would_cross_an_active_opposing_motion():
    board, engine, arbiter = make_engine("wR . . bR")
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(0, 3))

    first = engine.request_move(Position(0, 0), Position(0, 3))
    second = engine.request_move(Position(0, 3), Position(0, 0))

    assert first.is_accepted is True
    assert second.is_accepted is False
    assert second.reason == "route_conflict"

    # White had right of way (already moving first) - black is captured
    # immediately for trying to cross its path, not left alive to be
    # captured later on arrival.
    assert black_rook.state == CAPTURED
    assert board.get_piece(Position(0, 3)) is None

    engine.wait(3000)

    # White's motion is untouched by the rejected request and lands on the
    # now-empty cell black used to occupy.
    assert board.get_piece(Position(0, 3)) is white_rook
    assert board.get_piece(Position(0, 0)) is None
    assert black_rook.state == CAPTURED


def test_request_move_route_conflict_capture_notifies_observers_immediately():
    board, engine, arbiter = make_engine("wR . . bR")
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(0, 3))
    observer = RecordingObserver()
    engine.add_observer(observer)

    engine.request_move(Position(0, 0), Position(0, 3))
    engine.request_move(Position(0, 3), Position(0, 0))

    # Reported the moment the conflict resolves, not deferred until white's
    # motion later completes on wait() - white itself hasn't landed yet.
    assert observer.arrivals == [
        ArrivalEvent(piece=white_rook, captured_piece=black_rook, has_landed=False)
    ]


def test_request_move_route_conflict_capture_of_a_king_ends_the_game_immediately():
    # Black king starts off white rook's row entirely - its own one-square
    # move is what steps into the rook's already-active path, so this isn't
    # just a blocked slide (a king in the rook's own path would make the
    # first move itself illegal, not a route conflict).
    board, engine, arbiter = make_engine("wR . . .\n. bK . .")

    engine.request_move(Position(0, 0), Position(0, 3))
    engine.request_move(Position(1, 1), Position(0, 1))

    # No need to wait() for white's motion to land - the king already died
    # at request time, the instant it tried to cross white's active path.
    assert engine.game_over is True


def test_request_move_stops_a_same_color_piece_one_cell_short_of_a_crossing_path():
    board, engine, arbiter = make_engine(". . wR . .\n. . . . .\nwR . . . .\n. . . . .\n. . . . .")
    vertical_rook = board.get_piece(Position(0, 2))
    horizontal_rook = board.get_piece(Position(2, 0))

    first = engine.request_move(Position(0, 2), Position(4, 2))
    second = engine.request_move(Position(2, 0), Position(2, 4))

    assert first.is_accepted is True
    assert second.is_accepted is True

    # Both paths cross (2, 2) at exactly 2 * CELL_DURATION_MS - same color,
    # so the newly commanded rook stops one cell short instead of sharing
    # that cell, shortening its own motion to exactly 1 * CELL_DURATION_MS.
    engine.wait(CELL_DURATION_MS)
    assert board.get_piece(Position(2, 1)) is horizontal_rook
    # Stopping short of a teammate still counts as completing a motion.
    assert arbiter.is_in_cooldown(horizontal_rook) is True
    assert vertical_rook.state == MOVING


def test_request_move_rejects_outright_when_a_same_color_collision_leaves_no_safe_cell():
    board, engine, arbiter = make_engine("wR . . . wR")
    first_rook = board.get_piece(Position(0, 0))
    second_rook = board.get_piece(Position(0, 4))

    first = engine.request_move(Position(0, 0), Position(0, 3))
    engine.wait(2 * CELL_DURATION_MS)

    # first_rook has 1 cell left and they'd meet exactly one cell into
    # second_rook's travel - no cell short of that to stop at safely.
    second = engine.request_move(Position(0, 4), Position(0, 1))

    assert first.is_accepted is True
    assert second.is_accepted is False
    assert second.reason == "route_conflict"
    assert second_rook.state == IDLE
    assert len(arbiter.get_active_motions()) == 1


def test_wait_delegates_to_real_time_arbiter():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))

    engine.wait(1000)

    assert board.get_piece(Position(0, 1)) is not None
    assert arbiter.has_active_motion() is False


def test_king_capture_sets_game_over_flag():
    board, engine, arbiter = make_engine("wR . bK\n. . .\n. . .")

    engine.request_move(Position(0, 0), Position(0, 2))
    engine.wait(2000)

    assert engine.game_over is True


def test_king_capture_sets_game_over_even_while_another_motion_is_concurrently_active():
    board, engine, arbiter = make_engine("wR . bK\n. . .\nwR . .")

    engine.request_move(Position(0, 0), Position(0, 2))
    engine.request_move(Position(2, 0), Position(2, 2))
    engine.wait(2000)

    assert engine.game_over is True
    assert board.get_piece(Position(0, 2)) is not None
    assert board.get_piece(Position(2, 2)) is not None


def test_non_king_capture_does_not_set_game_over_flag():
    board, engine, arbiter = make_engine("wR . bP\n. . .\n. . .")

    engine.request_move(Position(0, 0), Position(0, 2))
    engine.wait(2000)

    assert engine.game_over is False


def test_request_jump_marks_the_piece_airborne():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")

    result = engine.request_jump(Position(1, 1))

    assert result.is_accepted is True
    assert result.reason == "ok"
    assert arbiter.is_airborne(board.get_piece(Position(1, 1))) is True


def test_request_jump_rejects_an_empty_cell():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")

    result = engine.request_jump(Position(0, 0))

    assert result.is_accepted is False
    assert result.reason == "empty_cell"


def test_request_jump_rejects_a_piece_that_is_already_moving():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))

    result = engine.request_jump(Position(1, 1))

    assert result.is_accepted is False
    assert result.reason == "piece_is_moving"
    assert board.get_piece(Position(1, 1)).state == MOVING


def test_request_move_rejects_a_piece_still_in_long_rest_right_after_finishing_a_motion():
    # Every ordinary arrival earns a long_rest (assets/pieces/*/states/move/
    # config.json's next_state_when_finished) - the piece can't act again
    # until it expires.
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))
    engine.wait(CELL_DURATION_MS)

    result = engine.request_move(Position(0, 1), Position(0, 0))

    assert result.is_accepted is False
    assert result.reason == "piece_in_cooldown"


def test_request_move_succeeds_again_once_the_long_rest_from_a_previous_move_expires():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))
    engine.wait(CELL_DURATION_MS)
    engine.wait(LONG_REST_DURATION_MS)

    result = engine.request_move(Position(0, 1), Position(0, 0))

    assert result.is_accepted is True


def test_request_move_rejects_a_piece_still_in_cooldown_after_landing_from_a_jump():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    engine.request_jump(Position(1, 1))
    engine.wait(AIRBORNE_DURATION_MS)

    result = engine.request_move(Position(1, 1), Position(0, 1))

    assert result.is_accepted is False
    assert result.reason == "piece_in_cooldown"


def test_request_jump_rejects_a_piece_still_in_cooldown_after_a_jump_expires():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    engine.request_jump(Position(1, 1))
    engine.wait(AIRBORNE_DURATION_MS)

    result = engine.request_jump(Position(1, 1))

    assert result.is_accepted is False
    assert result.reason == "piece_in_cooldown"


def test_request_jump_rejects_when_game_is_over():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    engine.game_over = True

    result = engine.request_jump(Position(1, 1))

    assert result.is_accepted is False
    assert result.reason == "game_over"


# can_select/is_same_color are the single gate Controller (input/controller.py)
# queries instead of reading Board/RealTimeArbiter itself - see its own
# docstring for why.


def test_can_select_is_true_for_an_idle_piece():
    board, engine, arbiter = make_engine("wK . .\n. . .\n. . .")

    assert engine.can_select(Position(0, 0)) is True


def test_can_select_is_false_for_an_empty_cell():
    board, engine, arbiter = make_engine("wK . .\n. . .\n. . .")

    assert engine.can_select(Position(1, 1)) is False


def test_can_select_is_false_for_a_piece_that_is_currently_moving():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))

    assert engine.can_select(Position(1, 1)) is False


def test_can_select_is_false_for_a_piece_that_is_currently_airborne():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    engine.request_jump(Position(1, 1))

    assert engine.can_select(Position(1, 1)) is False


def test_can_select_is_false_for_a_piece_still_in_cooldown_after_landing():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))
    engine.wait(CELL_DURATION_MS)

    assert engine.can_select(Position(0, 1)) is False


def test_is_same_color_is_true_for_two_pieces_of_the_same_color():
    board, engine, arbiter = make_engine("wK . wR\n. . .\n. . .")

    assert engine.is_same_color(Position(0, 0), Position(0, 2)) is True


def test_is_same_color_is_false_for_pieces_of_opposing_colors():
    board, engine, arbiter = make_engine("wK . bR\n. . .\n. . .")

    assert engine.is_same_color(Position(0, 0), Position(0, 2)) is False


def test_is_same_color_is_false_when_either_cell_is_empty():
    board, engine, arbiter = make_engine("wK . .\n. . .\n. . .")

    assert engine.is_same_color(Position(0, 0), Position(1, 1)) is False


def test_snapshot_exposes_piece_data_without_returning_the_piece_object():
    board, engine, arbiter = make_engine("wK . .\n. . .\n. . .")

    snapshot = engine.snapshot()

    assert snapshot.board_width == 3
    assert snapshot.board_height == 3
    assert len(snapshot.pieces) == 1
    piece_snapshot = snapshot.pieces[0]
    assert piece_snapshot.color == WHITE
    assert piece_snapshot.kind == KING
    assert not hasattr(piece_snapshot, "cell")


def test_snapshot_and_its_pieces_are_immutable():
    # GameSnapshot/PieceSnapshot are the view's read-only fact sheet (see
    # model/game_state.py) - nothing downstream should be able to mutate a
    # field back as if it were live GameEngine state. pieces is a tuple, not
    # a list, so frozen=True actually covers the whole snapshot, not just
    # its top-level fields.
    board, engine, arbiter = make_engine("wK . .\n. . .\n. . .")

    snapshot = engine.snapshot()

    assert isinstance(snapshot.pieces, tuple)
    with pytest.raises(FrozenInstanceError):
        snapshot.game_over = True
    with pytest.raises(FrozenInstanceError):
        snapshot.pieces[0].color = BLACK


def test_snapshot_includes_the_selected_cell_when_given():
    board, engine, arbiter = make_engine("wK . .\n. . .\n. . .")

    snapshot = engine.snapshot(selected=Position(0, 0))

    assert snapshot.selected_cell == Position(0, 0)


def test_snapshot_interpolates_board_position_for_a_piece_mid_motion():
    board, engine, arbiter = make_engine(". . .\n. . .\n. . .\nwR . .")
    engine.request_move(Position(3, 0), Position(1, 0))
    # A two-cell move's total duration is 2 * CELL_DURATION_MS, so waiting
    # exactly one CELL_DURATION_MS lands on a clean, constant-agnostic
    # halfway point regardless of what CELL_DURATION_MS itself is.
    arbiter.advance_time(CELL_DURATION_MS)

    snapshot = engine.snapshot()

    rook_snapshot = snapshot.pieces[0]
    assert rook_snapshot.row == 2.0
    assert rook_snapshot.col == 0.0


def test_snapshot_interpolates_board_position_independently_for_two_concurrent_motions():
    board, engine, arbiter = make_engine("wR . .\n. . .\nbR . .")
    engine.request_move(Position(0, 0), Position(0, 2))
    engine.request_move(Position(2, 0), Position(2, 2))
    # Both are two-cell moves - one CELL_DURATION_MS is exactly halfway.
    arbiter.advance_time(CELL_DURATION_MS)

    snapshot = engine.snapshot()
    pieces_by_color = {piece.color: piece for piece in snapshot.pieces}

    assert pieces_by_color[WHITE].row == 0.0
    assert pieces_by_color[WHITE].col == 1.0
    assert pieces_by_color[BLACK].row == 2.0
    assert pieces_by_color[BLACK].col == 1.0


def test_snapshot_reflects_game_over_flag():
    board, engine, arbiter = make_engine("wK . .\n. . .\n. . .")
    engine.game_over = True

    snapshot = engine.snapshot()

    assert snapshot.game_over is True


def test_snapshot_reports_idle_motion_phase_for_a_piece_that_has_not_acted():
    board, engine, arbiter = make_engine("wK . .\n. . .\n. . .")

    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.motion_phase == PHASE_IDLE


def test_snapshot_reports_move_motion_phase_while_a_motion_is_in_flight():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))

    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.motion_phase == PHASE_MOVE


def test_snapshot_reports_jump_motion_phase_while_a_piece_is_airborne():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    engine.request_jump(Position(1, 1))

    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.motion_phase == PHASE_JUMP


def test_snapshot_reports_long_rest_motion_phase_right_after_a_move_lands():
    # Resting is a real report, not collapsed back to PHASE_IDLE - a piece
    # on cooldown is blocked from acting just like a moving/airborne one.
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))
    engine.wait(CELL_DURATION_MS)

    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.motion_phase == PHASE_LONG_REST


def test_snapshot_reports_short_rest_motion_phase_right_after_a_jump_lands():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    engine.request_jump(Position(1, 1))
    engine.wait(AIRBORNE_DURATION_MS)

    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.motion_phase == PHASE_SHORT_REST


def test_snapshot_reports_idle_motion_phase_once_long_rest_expires():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))
    engine.wait(CELL_DURATION_MS)
    engine.wait(LONG_REST_DURATION_MS)

    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.motion_phase == PHASE_IDLE


def test_snapshot_reports_zero_cooldown_for_a_piece_that_has_not_acted():
    board, engine, arbiter = make_engine("wK . .\n. . .\n. . .")

    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.cooldown_remaining_ms == 0
    assert piece_snapshot.cooldown_total_ms == 0


def test_snapshot_reports_full_remaining_cooldown_right_after_a_move_lands():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))
    engine.wait(CELL_DURATION_MS)

    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.cooldown_remaining_ms == LONG_REST_DURATION_MS
    assert piece_snapshot.cooldown_total_ms == LONG_REST_DURATION_MS


def test_snapshot_reports_falling_remaining_cooldown_partway_through_a_rest():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))
    engine.wait(CELL_DURATION_MS)

    engine.wait(100)
    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.cooldown_remaining_ms == LONG_REST_DURATION_MS - 100
    assert piece_snapshot.cooldown_total_ms == LONG_REST_DURATION_MS


def test_snapshot_reports_zero_cooldown_once_long_rest_expires():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))
    engine.wait(CELL_DURATION_MS)
    engine.wait(LONG_REST_DURATION_MS)

    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.cooldown_remaining_ms == 0
    assert piece_snapshot.cooldown_total_ms == 0


def test_snapshot_reports_full_unavailable_window_the_instant_a_jump_launches():
    # A jump's total unavailable time spans its airborne hangtime plus the
    # short_rest that follows landing - reported from the moment the jump
    # is thrown, not only once short_rest itself starts (see
    # RealTimeArbiter.unavailable_progress's own docstring for why).
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    engine.request_jump(Position(1, 1))

    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.cooldown_remaining_ms == AIRBORNE_DURATION_MS + SHORT_REST_DURATION_MS
    assert piece_snapshot.cooldown_total_ms == AIRBORNE_DURATION_MS + SHORT_REST_DURATION_MS


def test_snapshot_reports_falling_cooldown_continuously_from_jump_through_its_short_rest():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    engine.request_jump(Position(1, 1))
    engine.wait(AIRBORNE_DURATION_MS)

    engine.wait(100)
    [piece_snapshot] = engine.snapshot().pieces

    assert piece_snapshot.cooldown_remaining_ms == SHORT_REST_DURATION_MS - 100
    assert piece_snapshot.cooldown_total_ms == AIRBORNE_DURATION_MS + SHORT_REST_DURATION_MS


def test_an_accepted_move_notifies_observers_with_the_move_facts():
    # GameEngine reports raw facts (color/kind/source/destination/
    # is_capture), never notation text - see model/game_state.py's
    # MoveLoggedEvent docstring for why building "Rb3"-style strings is
    # events/observers.py's job, not the engine's.
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    observer = RecordingObserver()
    engine.add_observer(observer)

    engine.request_move(Position(1, 1), Position(0, 1))

    [event] = observer.logged_moves
    assert event.color == WHITE
    assert event.kind == ROOK
    assert event.source == Position(1, 1)
    assert event.destination == Position(0, 1)
    assert event.is_capture is False
    assert event.is_jump is False
    assert event.elapsed_ms == 0


def test_a_rejected_move_does_not_notify_observers():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    observer = RecordingObserver()
    engine.add_observer(observer)

    engine.request_move(Position(1, 1), Position(2, 2))  # not a straight line - illegal

    assert observer.logged_moves == []


def test_a_capturing_moves_event_marks_is_capture_true():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. bP .")
    observer = RecordingObserver()
    engine.add_observer(observer)

    engine.request_move(Position(1, 1), Position(2, 1))

    [event] = observer.logged_moves
    assert event.is_capture is True


def test_a_move_logs_the_engines_own_elapsed_time_not_wall_clock_time():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    observer = RecordingObserver()
    engine.add_observer(observer)

    engine.wait(1234)
    engine.request_move(Position(1, 1), Position(0, 1))

    [event] = observer.logged_moves
    assert event.elapsed_ms == 1234


def test_an_accepted_jump_notifies_observers_with_is_jump_true_and_no_travel():
    # A jump has no destination (see RealTimeArbiter.start_jump) - source
    # and destination both report the piece's own cell.
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    observer = RecordingObserver()
    engine.add_observer(observer)

    engine.request_jump(Position(1, 1))

    [event] = observer.logged_moves
    assert event.color == WHITE
    assert event.kind == KING
    assert event.is_jump is True
    assert event.source == Position(1, 1)
    assert event.destination == Position(1, 1)


def test_a_rejected_jump_does_not_notify_observers():
    board, engine, arbiter = make_engine(". . .\n. . .\n. . .")
    observer = RecordingObserver()
    engine.add_observer(observer)

    engine.request_jump(Position(1, 1))  # empty cell

    assert observer.logged_moves == []


def test_wait_notifies_observers_of_every_arrival_including_non_captures():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    observer = RecordingObserver()
    engine.add_observer(observer)

    engine.request_move(Position(1, 1), Position(0, 1))
    engine.wait(CELL_DURATION_MS)

    [event] = observer.arrivals
    assert event.captured_piece is None


def test_a_piece_that_relocates_before_the_attacker_arrives_survives():
    # The defender's own destination cell is irrelevant to whether it can
    # flee - only its own state (idle, not mid-motion/airborne/resting)
    # gates request_move (see RuleEngine.validate_move) - so nothing stops
    # it from moving away while an enemy is still mid-flight toward it.
    # Capture is resolved lazily against the board's live state at the
    # attacker's actual arrival (RealTimeArbiter._resolve_arrival), not a
    # snapshot taken when the attack was requested - so a target that's
    # already gone by then is just... gone, and the attacker lands on the
    # now-empty square instead of capturing.
    board, engine, arbiter = make_engine("wR . . bR\n. . . .")
    observer = RecordingObserver()
    engine.add_observer(observer)

    attack = engine.request_move(Position(0, 0), Position(0, 3))
    assert attack.is_accepted is True

    engine.wait(200)  # white is now mid-flight, well short of column 3

    flee = engine.request_move(Position(0, 3), Position(1, 3))
    assert flee.is_accepted is True

    engine.wait(3 * CELL_DURATION_MS)  # long enough for both motions to land

    assert board.get_piece(Position(1, 3)).color == BLACK  # fled safely
    assert board.get_piece(Position(0, 3)).color == WHITE  # attacker lands on empty air
    assert all(event.captured_piece is None for event in observer.arrivals)


def test_wait_notifies_observers_of_a_captures_event_with_the_captured_piece():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. bP .")
    observer = RecordingObserver()
    engine.add_observer(observer)

    engine.request_move(Position(1, 1), Position(2, 1))
    engine.wait(CELL_DURATION_MS)

    [event] = observer.arrivals
    assert event.captured_piece.kind == PAWN


def test_move_log_reflects_where_a_move_actually_lands_after_a_mid_flight_interception():
    # End-to-end version of events/observers.py's own
    # test_move_log_observer_corrects_a_moves_notation_once_it_actually_lands_short_and_captures -
    # driven through the real request_move/wait pipeline (matching
    # test_real_time_arbiter.py's own
    # test_a_faster_enemy_piece_lands_in_a_slower_motions_path_and_intercepts_it_in_one_big_tick),
    # to prove GameEngine/RealTimeArbiter actually thread a real piece id
    # through far enough for MoveLogObserver to reconcile it.
    board, engine, arbiter = make_engine("wR . . . . .\n. . . bR . .")
    move_log = MoveLogObserver(board_height=board.height)
    engine.add_observer(move_log)

    engine.request_move(Position(0, 0), Position(0, 5))  # white: requests 5 cells
    engine.request_move(Position(1, 3), Position(0, 3))  # black: 1 cell, lands in white's path

    engine.wait(5 * CELL_DURATION_MS + 100)

    # White reaches its originally requested f-file square after all -
    # capturing black three cells in no longer stops it there (see
    # RealTimeArbiter's own test above for the full mechanics). The mid-
    # flight capture event has has_landed=False, so MoveLogObserver leaves
    # the entry pending until white's own later, genuine arrival - which
    # finds nothing left at (0, 5) to capture, so the notation shows the
    # true final destination without an "x" (a known simplification: this
    # display-only notation has no way to also mark a capture that happened
    # partway through a move that didn't end there).
    assert [entry.notation for entry in move_log.entries_for(WHITE)] == ["Rf2"]
    # Black's own move had already genuinely completed (landed, no capture)
    # before white's interception reached it a moment later - that earlier,
    # accurate entry is untouched, not dropped as if it never happened.
    assert [entry.notation for entry in move_log.entries_for(BLACK)] == ["Rd2"]


def test_multiple_observers_are_all_notified_of_the_same_move():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    first = RecordingObserver()
    second = RecordingObserver()
    engine.add_observer(first)
    engine.add_observer(second)

    engine.request_move(Position(1, 1), Position(0, 1))

    assert len(first.logged_moves) == 1
    assert len(second.logged_moves) == 1
