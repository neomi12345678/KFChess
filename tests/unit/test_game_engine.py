from engine.game_engine import GameEngine
from boardio.board_parser import parse
from model.piece import AIRBORNE, BLACK, CAPTURED, IDLE, KING, MOVING, WHITE
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine


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


def test_request_move_captures_an_opposing_piece_that_meets_it_head_on():
    board, engine, arbiter = make_engine("wR . . bR")
    white_rook = board.get_piece(Position(0, 0))
    black_rook = board.get_piece(Position(0, 3))

    first = engine.request_move(Position(0, 0), Position(0, 3))
    second = engine.request_move(Position(0, 3), Position(0, 0))

    assert first.is_accepted is True
    assert second.is_accepted is True

    engine.wait(1000)

    # They'd truly meet at column 1.5 after 1500ms - black only completes 1
    # full cell before that instant, and captures white there.
    assert board.get_piece(Position(0, 2)) is black_rook
    assert board.get_piece(Position(0, 0)) is None
    assert board.get_piece(Position(0, 3)) is None
    assert white_rook.state == CAPTURED


def test_request_move_stops_a_same_color_piece_one_cell_short_of_a_crossing_path():
    board, engine, arbiter = make_engine(". . wR . .\n. . . . .\nwR . . . .\n. . . . .\n. . . . .")
    vertical_rook = board.get_piece(Position(0, 2))
    horizontal_rook = board.get_piece(Position(2, 0))

    first = engine.request_move(Position(0, 2), Position(4, 2))
    second = engine.request_move(Position(2, 0), Position(2, 4))

    assert first.is_accepted is True
    assert second.is_accepted is True

    engine.wait(1000)

    # Both paths cross (2, 2) at exactly 2000ms - same color, so the newly
    # commanded rook stops one cell short instead of sharing that cell.
    assert board.get_piece(Position(2, 1)) is horizontal_rook
    assert horizontal_rook.state == IDLE
    assert vertical_rook.state == MOVING


def test_request_move_rejects_outright_when_a_same_color_collision_leaves_no_safe_cell():
    board, engine, arbiter = make_engine("wR . . . wR")
    first_rook = board.get_piece(Position(0, 0))
    second_rook = board.get_piece(Position(0, 4))

    first = engine.request_move(Position(0, 0), Position(0, 3))
    engine.wait(2000)

    # first_rook has 1 cell left and they'd meet exactly 1000ms into
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
    assert board.get_piece(Position(1, 1)).state == AIRBORNE


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


def test_request_move_rejects_a_piece_still_in_cooldown_after_finishing_a_motion():
    board, engine, arbiter = make_engine(". . .\n. wR .\n. . .")
    engine.request_move(Position(1, 1), Position(0, 1))
    engine.wait(1000)

    result = engine.request_move(Position(0, 1), Position(0, 0))

    assert result.is_accepted is False
    assert result.reason == "piece_in_cooldown"


def test_request_jump_rejects_a_piece_still_in_cooldown_after_a_jump_expires():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    engine.request_jump(Position(1, 1))
    engine.wait(1000)

    result = engine.request_jump(Position(1, 1))

    assert result.is_accepted is False
    assert result.reason == "piece_in_cooldown"


def test_request_jump_rejects_when_game_is_over():
    board, engine, arbiter = make_engine(". . .\n. wK .\n. . .")
    engine.game_over = True

    result = engine.request_jump(Position(1, 1))

    assert result.is_accepted is False
    assert result.reason == "game_over"


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


def test_snapshot_includes_the_selected_cell_when_given():
    board, engine, arbiter = make_engine("wK . .\n. . .\n. . .")

    snapshot = engine.snapshot(selected=Position(0, 0))

    assert snapshot.selected_cell == Position(0, 0)


def test_snapshot_interpolates_pixels_for_a_piece_mid_motion():
    board, engine, arbiter = make_engine(". . .\n. . .\n. . .\nwR . .")
    engine.request_move(Position(3, 0), Position(1, 0))
    arbiter.advance_time(500)

    snapshot = engine.snapshot()

    rook_snapshot = snapshot.pieces[0]
    assert rook_snapshot.pixel_x == 50
    assert rook_snapshot.pixel_y == 300


def test_snapshot_interpolates_pixels_independently_for_two_concurrent_motions():
    board, engine, arbiter = make_engine("wR . .\n. . .\nbR . .")
    engine.request_move(Position(0, 0), Position(0, 2))
    engine.request_move(Position(2, 0), Position(2, 2))
    arbiter.advance_time(500)

    snapshot = engine.snapshot()
    pieces_by_color = {piece.color: piece for piece in snapshot.pieces}

    assert pieces_by_color[WHITE].pixel_x == 100
    assert pieces_by_color[WHITE].pixel_y == 50
    assert pieces_by_color[BLACK].pixel_x == 100
    assert pieces_by_color[BLACK].pixel_y == 250


def test_snapshot_reflects_game_over_flag():
    board, engine, arbiter = make_engine("wK . .\n. . .\n. . .")
    engine.game_over = True

    snapshot = engine.snapshot()

    assert snapshot.game_over is True
