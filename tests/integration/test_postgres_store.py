"""Real PostgreSQL, no mocks - the same convention every SQLite-backed test
in this project already follows (see tests/unit/test_user_store.py,
tests/unit/test_rating_store.py, tests/unit/test_server_rooms.py, which
these largely mirror). Skipped unless KFCHESS_TEST_DATABASE_URL points at a
real, reachable Postgres - `docker compose up -d postgres` then

    KFCHESS_TEST_DATABASE_URL=postgresql://kfchess:kfchess@localhost:55432/kfchess \
        python -m pytest tests/integration/test_postgres_store.py

(55432, not Postgres's usual 5432 - see docker-compose.yml's own comment on
why: this machine already has a standalone Postgres bound to the real 5432.)
so the default `python -m pytest` stays infra-free, matching this
project's existing "just run it" story.
"""

import os

import psycopg
import pytest

from server.accounts import InvalidCredentialsError
from server.postgres.accounts import PostgresRatingStore, PostgresUserStore, open_postgres_accounts_database
from server.postgres.game_history import PostgresGameHistoryStore
from server.postgres.rooms import PostgresRoomStore
from server.rooms import RoomRegistry
from server.server_config import STARTING_RATING

DSN = os.environ.get("KFCHESS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DSN is None, reason="set KFCHESS_TEST_DATABASE_URL to a real Postgres DSN to run these"
)


@pytest.fixture
def database():
    db = open_postgres_accounts_database(DSN)
    db.connection.execute("TRUNCATE accounts")
    db.connection.commit()
    yield db
    db.connection.close()


@pytest.fixture
def user_store(database):
    return PostgresUserStore(database)


@pytest.fixture
def rating_store(database):
    # Rows only ever exist once PostgresUserStore.login has created them -
    # same assumption tests/unit/test_rating_store.py's own fixture makes
    # against the SQLite RatingStore.
    PostgresUserStore(database).login("alice", "secret123")
    return PostgresRatingStore(database)


def test_first_login_for_a_username_registers_it(user_store):
    account = user_store.login("alice", "secret123")

    assert account.username == "alice"


def test_a_returning_username_with_the_correct_password_logs_in(user_store):
    user_store.login("alice", "secret123")

    account = user_store.login("alice", "secret123")

    assert account.username == "alice"


def test_a_returning_username_with_the_wrong_password_is_rejected(user_store):
    user_store.login("alice", "secret123")

    with pytest.raises(InvalidCredentialsError):
        user_store.login("alice", "wrong-password")


def test_rating_for_reads_the_starting_rating_right_after_registration(rating_store):
    assert rating_store.rating_for("alice") == STARTING_RATING


def test_update_rating_persists_the_new_value(rating_store):
    rating_store.update_rating("alice", 1250)

    assert rating_store.rating_for("alice") == 1250


# Simulates two shards racing to register the same brand-new username at
# once (server/postgres/__init__.py's own commit_or_rollback docstring) -
# two separate connections, since a single process's own lock
# (PostgresAccountsDatabase.lock) already serializes every call made
# through one UserStore instance and could never reproduce the race a
# second, independent shard connection actually causes.
def test_a_register_race_does_not_leave_the_losing_connection_stuck(database):
    database.connection.execute("TRUNCATE accounts")
    database.connection.commit()
    other_database = open_postgres_accounts_database(DSN)
    try:
        store_a = PostgresUserStore(database)
        store_b = PostgresUserStore(other_database)

        store_a._register("race_user", "secret123")

        with pytest.raises(psycopg.errors.UniqueViolation):
            store_b._register("race_user", "a-different-password")

        # other_database's connection must still be usable afterward -
        # exactly what commit_or_rollback's own rollback() on the exception
        # path guarantees; before it existed, this next query would fail
        # with InFailedSqlTransaction instead, since nothing had ever rolled
        # back the aborted transaction the UniqueViolation above left open.
        account = store_b.login("race_user", "secret123")
        assert account.username == "race_user"
    finally:
        other_database.connection.close()


@pytest.fixture
def room_store():
    store = PostgresRoomStore(DSN)
    with psycopg.connect(DSN) as connection:
        connection.execute("TRUNCATE room_spectators, rooms")
        connection.commit()
    yield store
    store.close()


def test_load_all_on_a_fresh_store_is_empty(room_store):
    assert room_store.load_all() == []


def test_save_then_load_all_round_trips_opponent_and_spectators(room_store):
    registry = RoomRegistry(store=room_store)
    room = registry.create("alice")
    registry.join(room.room_id, "bob")
    registry.join(room.room_id, "carol")

    [loaded] = room_store.load_all()

    assert loaded == {"room_id": room.room_id, "creator": "alice", "opponent": "bob", "spectators": {"carol"}}


def test_delete_removes_the_room_and_its_spectators(room_store):
    registry = RoomRegistry(store=room_store)
    room = registry.create("alice")
    registry.join(room.room_id, "bob")

    registry.close(room.room_id)

    assert room_store.load_all() == []


def test_a_new_registry_over_the_same_store_reconstructs_opponent_and_spectators(room_store):
    first = RoomRegistry(store=room_store)
    room = first.create("alice")
    first.join(room.room_id, "bob")
    first.join(room.room_id, "carol")

    restarted = RoomRegistry(store=room_store)

    reloaded = restarted.room_for_username("alice")
    assert reloaded.room_id == room.room_id
    assert reloaded.opponent == "bob"
    assert reloaded.spectators == {"carol"}


@pytest.fixture
def game_history_store():
    store = PostgresGameHistoryStore(DSN)
    with psycopg.connect(DSN) as connection:
        connection.execute("TRUNCATE game_history")
        connection.commit()
    yield store
    store.close()


def test_all_games_on_a_fresh_store_is_empty(game_history_store):
    assert game_history_store.all_games() == []


def test_record_game_round_trips_all_fields(game_history_store):
    game_history_store.record_game("play-abc123", "room-1", "alice", "bob", 1214, 1186)

    [game] = game_history_store.all_games()
    assert game == {
        "game_id": "play-abc123",
        "room_id": "room-1",
        "white_username": "alice",
        "black_username": "bob",
        "white_rating": 1214,
        "black_rating": 1186,
    }


def test_record_game_with_no_room_id_stores_null(game_history_store):
    game_history_store.record_game("play-def456", None, "alice", "bob", 1200, 1200)

    [game] = game_history_store.all_games()
    assert game["room_id"] is None


def test_recording_the_same_game_id_twice_is_a_no_op(game_history_store):
    game_history_store.record_game("play-abc123", "room-1", "alice", "bob", 1214, 1186)

    game_history_store.record_game("play-abc123", "room-1", "alice", "bob", 9999, 9999)  # must not raise or overwrite

    [game] = game_history_store.all_games()
    assert game["white_rating"] == 1214
    assert game["black_rating"] == 1186


# Server_Design.md §8's own "Persistence Workers consume it in batches" -
# services/persistence_worker/main.py's own record_games_batch call, one
# executemany + one commit for the whole batch.
def test_record_games_batch_records_every_game(game_history_store):
    game_history_store.record_games_batch(
        [
            ("batch-1", "room-1", "alice", "bob", 1214, 1186),
            ("batch-2", None, "carol", "dave", 1300, 1250),
        ]
    )

    game_ids = {game["game_id"] for game in game_history_store.all_games()}
    assert game_ids == {"batch-1", "batch-2"}


def test_record_games_batch_with_an_empty_list_is_a_no_op(game_history_store):
    game_history_store.record_games_batch([])

    assert game_history_store.all_games() == []


def test_record_games_batch_skips_an_already_recorded_game_id(game_history_store):
    game_history_store.record_game("batch-dup", "room-1", "alice", "bob", 1214, 1186)

    game_history_store.record_games_batch([("batch-dup", "room-1", "alice", "bob", 9999, 9999)])

    [game] = game_history_store.all_games()
    assert game["white_rating"] == 1214
