"""Real Postgres, no mocks - the standalone Persistence Worker service
(services/persistence_worker/main.py). Calls _on_game_finished directly with a fake
game.finished message the same shape server/nats/lifecycle.py's
NatsLifecyclePublisher.game_finished actually publishes, asserts a real
row lands in Postgres via PostgresGameHistoryStore - see
services/persistence_worker/main.py's own docstring on why this write is decoupled
from the Game Server Shard's own tick loop rather than a replacement for
the existing synchronous rating write.

Skipped unless KFCHESS_TEST_DATABASE_URL is set - `docker compose up -d postgres` then

    KFCHESS_TEST_DATABASE_URL=postgresql://kfchess:kfchess@localhost:55432/kfchess \
        python -m pytest tests/unit/test_persistence_worker_service.py

so the default `python -m pytest` stays infra-free.
"""

import json
import os

import pytest

DSN = os.environ.get("KFCHESS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(DSN is None, reason="set KFCHESS_TEST_DATABASE_URL to run these")


class _FakeMsg:
    def __init__(self, data: bytes):
        self.data = data


@pytest.fixture
def store():
    import psycopg

    from server.postgres.game_history import PostgresGameHistoryStore

    game_history_store = PostgresGameHistoryStore(DSN)
    with psycopg.connect(DSN) as connection:
        connection.execute("TRUNCATE game_history")
        connection.commit()
    yield game_history_store
    game_history_store.close()


def _fake_game_finished_msg(game_id="play-a1b2c3d4", room_id=None, white="alice", black="bob", ratings=None):
    payload = {
        "game_id": game_id,
        "room_id": room_id,
        "white_username": white,
        "black_username": black,
        "ratings": ratings or {"white": 1214, "black": 1186},
    }
    return _FakeMsg(json.dumps(payload).encode("utf-8"))


def test_on_game_finished_records_a_real_row(store):
    import asyncio

    from services.persistence_worker.main import _on_game_finished

    asyncio.run(_on_game_finished(store, _fake_game_finished_msg()))

    [game] = store.all_games()
    assert game["game_id"] == "play-a1b2c3d4"
    assert game["white_username"] == "alice"
    assert game["black_username"] == "bob"
    assert game["white_rating"] == 1214
    assert game["black_rating"] == 1186


def test_on_game_finished_with_a_room_id_records_it(store):
    import asyncio

    from services.persistence_worker.main import _on_game_finished

    asyncio.run(_on_game_finished(store, _fake_game_finished_msg(game_id="room-game-1", room_id="room-42")))

    [game] = store.all_games()
    assert game["room_id"] == "room-42"


def test_on_game_finished_twice_for_the_same_game_id_is_a_no_op(store):
    import asyncio

    from services.persistence_worker.main import _on_game_finished

    asyncio.run(_on_game_finished(store, _fake_game_finished_msg(ratings={"white": 1214, "black": 1186})))
    asyncio.run(_on_game_finished(store, _fake_game_finished_msg(ratings={"white": 9999, "black": 9999})))

    assert len(store.all_games()) == 1
