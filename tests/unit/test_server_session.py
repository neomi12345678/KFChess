import pytest

from boardio.board_parser import parse
from logic_config import MOVE_CELL_DURATION_MS
from model.game_state import GameSnapshot
from model.piece import BLACK, WHITE
from model.position import Position
from server.accounts import AccountStore
from server.protocol import JUMP, MOVE, Command
from server.session import DISCONNECT_GRACE_MS, GameSession


@pytest.fixture
def account_store():
    store = AccountStore(":memory:")
    store.login("alice", "secret123")
    store.login("bob", "hunter2")
    yield store
    store.close()


def make_session(board_text, account_store, white_username="alice", black_username="bob"):
    return GameSession(parse(board_text), account_store, white_username, black_username)


def test_constructor_records_both_usernames_by_seat(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)

    assert session.username_for(WHITE) == "alice"
    assert session.username_for(BLACK) == "bob"
    assert session.seat_for_username("alice") == WHITE
    assert session.seat_for_username("bob") == BLACK


def test_seat_for_an_unknown_username_is_none(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)

    assert session.seat_for_username("nobody") is None


def test_apply_command_accepts_a_move_for_the_matching_color(account_store):
    # A rook, not a king - a king can only step one square (see
    # rules/piece_rules.py's KingRule), so a 2-square move needs a piece
    # whose rules actually allow it.
    session = make_session("wR . .\n. . .\n. . .", account_store)
    command = Command(color=WHITE, kind=MOVE, source=Position(0, 0), destination=Position(0, 2))

    result = session.apply_command(command)

    assert result.is_accepted is True


def test_apply_command_rejects_a_move_for_a_piece_of_the_wrong_color(account_store):
    session = make_session("wK . bR\n. . .\n. . .", account_store)
    # Claims to be black, but the piece sitting at (0, 0) is white - moving
    # someone else's piece must never reach GameEngine at all.
    command = Command(color=BLACK, kind=MOVE, source=Position(0, 0), destination=Position(0, 1))

    result = session.apply_command(command)

    assert result.is_accepted is False
    assert result.reason == "not_your_piece"


def test_apply_command_rejects_a_move_from_an_empty_cell(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)
    command = Command(color=WHITE, kind=MOVE, source=Position(1, 1), destination=Position(1, 2))

    result = session.apply_command(command)

    assert result.is_accepted is False
    assert result.reason == "not_your_piece"


def test_apply_command_accepts_a_jump_for_the_matching_color(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)
    command = Command(color=WHITE, kind=JUMP, source=Position(0, 0), destination=None)

    result = session.apply_command(command)

    assert result.is_accepted is True


def test_apply_command_rejects_a_jump_for_the_wrong_color(account_store):
    session = make_session("wK . bR\n. . .\n. . .", account_store)
    command = Command(color=WHITE, kind=JUMP, source=Position(0, 2), destination=None)

    result = session.apply_command(command)

    assert result.is_accepted is False
    assert result.reason == "not_your_piece"


def test_tick_advances_the_real_game_engines_clock_and_the_move_actually_arrives(account_store):
    board = parse("wR . .\n. . .\n. . .")
    session = GameSession(board, account_store, "alice", "bob")
    session.apply_command(Command(color=WHITE, kind=MOVE, source=Position(0, 0), destination=Position(0, 2)))

    session.tick(MOVE_CELL_DURATION_MS * 2 + 1)

    assert board.get_piece(Position(0, 0)) is None
    assert board.get_piece(Position(0, 2)) is not None


def test_snapshot_reflects_the_real_boards_pieces(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)

    snapshot = session.snapshot()

    assert isinstance(snapshot, GameSnapshot)
    assert snapshot.board_width == 3
    assert snapshot.board_height == 3
    assert len(snapshot.pieces) == 1
    assert snapshot.pieces[0].color == WHITE


def test_a_seat_starts_out_connected(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)

    assert session.is_disconnected(WHITE) is False
    assert session.seconds_remaining_for(WHITE) is None


def test_mark_disconnected_starts_the_grace_timer(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)

    session.mark_disconnected(WHITE)

    assert session.is_disconnected(WHITE) is True
    assert session.seconds_remaining_for(WHITE) == DISCONNECT_GRACE_MS // 1000


def test_mark_reconnected_cancels_the_grace_timer(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)
    session.mark_disconnected(WHITE)

    session.mark_reconnected(WHITE)

    assert session.is_disconnected(WHITE) is False
    assert session.seconds_remaining_for(WHITE) is None


def test_advance_disconnect_grace_counts_down_the_remaining_seconds(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)
    session.mark_disconnected(WHITE)

    session.advance_disconnect_grace(5_000)

    assert session.seconds_remaining_for(WHITE) == 15


def test_advance_disconnect_grace_returns_none_before_the_grace_period_ends(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)
    session.mark_disconnected(WHITE)

    expired = session.advance_disconnect_grace(DISCONNECT_GRACE_MS - 1)

    assert expired is None


def test_advance_disconnect_grace_reports_the_seat_once_the_grace_period_ends(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)
    session.mark_disconnected(WHITE)

    expired = session.advance_disconnect_grace(DISCONNECT_GRACE_MS)

    assert expired == WHITE


def test_advance_disconnect_grace_ignores_seats_that_are_still_connected(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)

    expired = session.advance_disconnect_grace(DISCONNECT_GRACE_MS)

    assert expired is None


def test_resign_ends_the_game_and_records_the_loser(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)

    session.resign(WHITE)

    assert session.game_engine.game_over is True


def test_finalize_ratings_returns_none_while_the_game_is_still_in_progress(account_store):
    session = make_session("wK . .\n. . bK", account_store)

    assert session.finalize_ratings_if_game_over() is None


def test_finalize_ratings_after_a_resignation_updates_and_persists_both_accounts(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)

    session.resign(WHITE)  # white disconnected and ran out the grace period
    rating_update = session.finalize_ratings_if_game_over()

    assert rating_update == {WHITE: 1184, BLACK: 1216}
    assert account_store.rating_for("alice") == 1184
    assert account_store.rating_for("bob") == 1216


def test_finalize_ratings_updates_and_persists_both_accounts_after_a_king_capture(account_store):
    # A 1x2 board: white rook right next to black's king - one move
    # captures it and ends the game (see rules.rule_engine.KingCaptureWinCondition).
    session = make_session("wR bK", account_store)

    session.apply_command(Command(color=WHITE, kind=MOVE, source=Position(0, 0), destination=Position(0, 1)))
    session.tick(MOVE_CELL_DURATION_MS + 1)

    assert session.game_engine.game_over is True

    rating_update = session.finalize_ratings_if_game_over()

    assert rating_update == {WHITE: 1216, BLACK: 1184}
    assert account_store.rating_for("alice") == 1216
    assert account_store.rating_for("bob") == 1184


def test_apply_command_populates_the_real_move_log_and_score_observers(account_store):
    # A 1x2 board: white rook right next to a black pawn (not a king - see
    # model.piece.PIECE_VALUES, a captured king is worth 0 points, since
    # that capture already ends the game via a resignation/rating path, not
    # a score one) - one move both logs a move-log entry and, once it
    # lands, credits white's score - the same MoveLogObserver/ScoreObserver
    # play.py wires up locally (see events/observers.py), here fed by the
    # server's own GameEngine instead.
    session = make_session("wR bP", account_store)

    session.apply_command(Command(color=WHITE, kind=MOVE, source=Position(0, 0), destination=Position(0, 1)))

    [entry] = session.move_log.entries_for(WHITE)
    assert entry.notation == "Rxb1"

    session.tick(MOVE_CELL_DURATION_MS + 1)

    assert session.score.score_for(WHITE) == 1


def test_drain_wire_events_reports_a_plain_move_as_move_logged_not_a_jump(account_store):
    session = make_session("wR . .\n. . .\n. . .", account_store)

    session.apply_command(Command(color=WHITE, kind=MOVE, source=Position(0, 0), destination=Position(0, 2)))

    assert session.drain_wire_events() == [{"type": "move_logged", "is_jump": False}]


def test_drain_wire_events_reports_a_jump_as_move_logged_with_is_jump_true(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)

    session.apply_command(Command(color=WHITE, kind=JUMP, source=Position(0, 0), destination=None))

    assert session.drain_wire_events() == [{"type": "move_logged", "is_jump": True}]


def test_drain_wire_events_reports_a_capture_once_the_piece_actually_arrives(account_store):
    # A 1x2 board: white rook right next to a black pawn - the capture only
    # resolves (and thus only buffers a "capture" wire event) once the move
    # actually lands, on tick(), not at request time.
    session = make_session("wR bP", account_store)
    session.apply_command(Command(color=WHITE, kind=MOVE, source=Position(0, 0), destination=Position(0, 1)))

    assert session.drain_wire_events() == [{"type": "move_logged", "is_jump": False}]

    session.tick(MOVE_CELL_DURATION_MS + 1)

    assert session.drain_wire_events() == [{"type": "capture"}]


def test_drain_wire_events_is_empty_when_nothing_happened(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)

    assert session.drain_wire_events() == []


def test_drain_wire_events_clears_the_buffer_once_read(account_store):
    session = make_session("wR . .\n. . .\n. . .", account_store)
    session.apply_command(Command(color=WHITE, kind=MOVE, source=Position(0, 0), destination=Position(0, 2)))

    session.drain_wire_events()

    assert session.drain_wire_events() == []


def test_finalize_ratings_only_ever_applies_once(account_store):
    session = make_session("wK . .\n. . .\n. . .", account_store)
    session.resign(WHITE)

    first = session.finalize_ratings_if_game_over()
    second = session.finalize_ratings_if_game_over()

    assert first is not None
    assert second is None
    # A second call must never re-apply the ELO delta on top of itself.
    assert account_store.rating_for("bob") == 1216
