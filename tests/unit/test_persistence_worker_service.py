"""Real Postgres, no mocks - the standalone Persistence Worker service
(services/persistence_worker/main.py). Calls _flush_batch directly with fake
game.finished payloads the same shape server/nats/lifecycle.py's
NatsLifecyclePublisher.game_finished actually publishes, asserts real rows
land in Postgres via PostgresGameHistoryStore.record_games_batch - see
services/persistence_worker/main.py's own docstring on why this write is
decoupled from the Game Server Shard's own tick loop (batched, not one
INSERT per game) rather than a replacement for the existing synchronous
rating write.

Skipped unless KFCHESS_TEST_DATABASE_URL is set - `docker compose up -d postgres` then

    KFCHESS_TEST_DATABASE_URL=postgresql://kfchess:kfchess@localhost:55432/kfchess \
        python -m pytest tests/unit/test_persistence_worker_service.py

so the default `python -m pytest` stays infra-free.
"""

import os

import pytest

DSN = os.environ.get("KFCHESS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(DSN is None, reason="set KFCHESS_TEST_DATABASE_URL to run these")


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


def _fake_game_finished_payload(
    game_id="play-a1b2c3d4", room_id=None, white="alice", black="bob", ratings=None, published_at=None
):
    payload = {
        "game_id": game_id,
        "room_id": room_id,
        "white_username": white,
        "black_username": black,
        "ratings": ratings or {"white": 1214, "black": 1186},
    }
    if published_at is not None:
        payload["published_at"] = published_at
    return payload


def test_flush_batch_records_a_real_row(store):
    from services.persistence_worker.main import _flush_batch

    _flush_batch(store, [_fake_game_finished_payload()])

    [game] = store.all_games()
    assert game["game_id"] == "play-a1b2c3d4"
    assert game["white_username"] == "alice"
    assert game["black_username"] == "bob"
    assert game["white_rating"] == 1214
    assert game["black_rating"] == 1186


def test_flush_batch_with_a_room_id_records_it(store):
    from services.persistence_worker.main import _flush_batch

    _flush_batch(store, [_fake_game_finished_payload(game_id="room-game-1", room_id="room-42")])

    [game] = store.all_games()
    assert game["room_id"] == "room-42"


def test_flush_batch_records_every_game_in_the_batch(store):
    from services.persistence_worker.main import _flush_batch

    _flush_batch(
        store,
        [
            _fake_game_finished_payload(game_id="batch-game-1", white="alice", black="bob"),
            _fake_game_finished_payload(game_id="batch-game-2", white="carol", black="dave"),
            _fake_game_finished_payload(game_id="batch-game-3", white="erin", black="frank"),
        ],
    )

    game_ids = {game["game_id"] for game in store.all_games()}
    assert game_ids == {"batch-game-1", "batch-game-2", "batch-game-3"}


def test_flush_batch_twice_for_the_same_game_id_is_a_no_op(store):
    from services.persistence_worker.main import _flush_batch

    _flush_batch(store, [_fake_game_finished_payload(ratings={"white": 1214, "black": 1186})])
    _flush_batch(store, [_fake_game_finished_payload(ratings={"white": 9999, "black": 9999})])

    assert len(store.all_games()) == 1


# Server_Design.md §9's own "consumer lag per Persistence Worker" metric -
# published_at is a newer field (see server/nats/lifecycle.py's own
# NatsLifecyclePublisher.game_finished); read defensively so an older
# payload without it still records the game, just without moving the gauge.
# Reflects the *oldest* item in the batch - the longest anything waited.
def test_flush_batch_with_published_at_updates_the_lag_gauge(store):
    import time

    from services.persistence_worker.main import _LAG_GAUGE, _flush_batch

    published_at = time.time() - 2.0  # published ~2s ago
    _flush_batch(store, [_fake_game_finished_payload(published_at=published_at)])

    assert _LAG_GAUGE._value.get() >= 2.0


def test_flush_batch_without_published_at_does_not_crash(store):
    from services.persistence_worker.main import _flush_batch

    _flush_batch(store, [_fake_game_finished_payload(game_id="play-no-timestamp")])

    [game] = store.all_games()
    assert game["game_id"] == "play-no-timestamp"


# Proves the actual queue-draining behavior _run_batch_flusher/_collect_batch
# provide, not just the flush-a-given-list-of-payloads half above: enough
# items to hit batch_size flush in one pass, and a lone item that only
# flushes once flush_interval_s elapses (a quiet period must not leave a
# small batch waiting forever).
def test_batch_flusher_flushes_once_batch_size_is_reached(store):
    import asyncio

    from services.persistence_worker.main import _collect_batch

    async def scenario():
        queue = asyncio.Queue()
        for i in range(3):
            await queue.put(_fake_game_finished_payload(game_id=f"size-game-{i}"))
        # flush_interval_s is generous - this must return the instant
        # batch_size is reached, not wait it out.
        return await asyncio.wait_for(_collect_batch(queue, batch_size=3, flush_interval_s=30.0), timeout=2.0)

    batch = asyncio.run(scenario())
    assert len(batch) == 3


def test_batch_flusher_flushes_a_partial_batch_after_the_interval(store):
    import asyncio

    from services.persistence_worker.main import _collect_batch

    async def scenario():
        queue = asyncio.Queue()
        await queue.put(_fake_game_finished_payload(game_id="lone-game"))
        # batch_size is never reached (only one item ever arrives) - this
        # must still return once flush_interval_s elapses, not hang.
        return await asyncio.wait_for(_collect_batch(queue, batch_size=50, flush_interval_s=0.2), timeout=2.0)

    batch = asyncio.run(scenario())
    assert len(batch) == 1
    assert batch[0]["game_id"] == "lone-game"
