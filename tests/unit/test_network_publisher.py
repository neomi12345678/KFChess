import pytest

from boardio.board_parser import parse
from logic_config import MOVE_CELL_DURATION_MS
from model.piece import WHITE
from model.position import Position
from protocol.game_messages import CaptureMessage, MoveLoggedMessage
from server.accounts import UserStore
from server.accounts_db import open_accounts_database
from server.protocol import JUMP, MOVE, Command
from server.publisher import NetworkPublisher
from server.rating_store import RatingStore
from server.session import GameSession


@pytest.fixture
def rating_store():
    database = open_accounts_database(":memory:")
    user_store = UserStore(database)
    user_store.login("alice", "secret123")
    user_store.login("bob", "hunter2")
    return RatingStore(database)


def make_session(board_text, rating_store, white_username="alice", black_username="bob"):
    return GameSession(parse(board_text), rating_store, white_username, black_username)


def test_drain_reports_a_plain_move_as_move_logged_not_a_jump(rating_store):
    session = make_session("wR . .\n. . .\n. . .", rating_store)
    publisher = NetworkPublisher(session.bus)

    session.apply_command(Command(color=WHITE, kind=MOVE, source=Position(0, 0), destination=Position(0, 2)))

    assert publisher.drain() == [MoveLoggedMessage(is_jump=False)]


def test_drain_reports_a_jump_as_move_logged_with_is_jump_true(rating_store):
    session = make_session("wK . .\n. . .\n. . .", rating_store)
    publisher = NetworkPublisher(session.bus)

    session.apply_command(Command(color=WHITE, kind=JUMP, source=Position(0, 0), destination=None))

    assert publisher.drain() == [MoveLoggedMessage(is_jump=True)]


def test_drain_reports_a_capture_once_the_piece_actually_arrives(rating_store):
    # A 1x2 board: white rook right next to a black pawn - the capture only
    # resolves (and thus only buffers a "capture" wire event) once the move
    # actually lands, on tick(), not at request time.
    session = make_session("wR bP", rating_store)
    publisher = NetworkPublisher(session.bus)
    session.apply_command(Command(color=WHITE, kind=MOVE, source=Position(0, 0), destination=Position(0, 1)))

    assert publisher.drain() == [MoveLoggedMessage(is_jump=False)]

    session.tick(MOVE_CELL_DURATION_MS + 1)

    assert publisher.drain() == [CaptureMessage()]


def test_drain_is_empty_when_nothing_happened(rating_store):
    session = make_session("wK . .\n. . .\n. . .", rating_store)
    publisher = NetworkPublisher(session.bus)

    assert publisher.drain() == []


def test_drain_clears_the_buffer_once_read(rating_store):
    session = make_session("wR . .\n. . .\n. . .", rating_store)
    publisher = NetworkPublisher(session.bus)
    session.apply_command(Command(color=WHITE, kind=MOVE, source=Position(0, 0), destination=Position(0, 2)))

    publisher.drain()

    assert publisher.drain() == []
