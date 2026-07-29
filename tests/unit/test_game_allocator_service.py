"""Real Redis + real NATS, no mocks - the standalone Game Allocator service
(services/game_allocator/main.py). Publishes a fake match.found the same shape the
Matchmaker service produces, asserts game.allocated comes out with a real
lease actually held in Redis (not faked) - see services/game_allocator/main.py's
own docstring on why the lease matters even with exactly one shard.

Skipped unless both KFCHESS_TEST_REDIS_URL and KFCHESS_TEST_NATS_URL are
set - `docker compose up -d redis nats` then

    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 \
    KFCHESS_TEST_NATS_URL=nats://localhost:4222 \
        python -m pytest tests/unit/test_game_allocator_service.py

so the default `python -m pytest` stays infra-free.
"""

import asyncio
import json
import os

import pytest

REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")
NATS_URL = os.environ.get("KFCHESS_TEST_NATS_URL")
pytestmark = pytest.mark.skipif(
    REDIS_URL is None or NATS_URL is None,
    reason="set KFCHESS_TEST_REDIS_URL and KFCHESS_TEST_NATS_URL to run these",
)


class _FakeMsg:
    def __init__(self, data: bytes):
        self.data = data


def test_match_found_is_allocated_with_a_real_lease():
    import nats
    import redis as redis_lib

    from services.game_allocator.main import _handle_match_found

    async def scenario():
        redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        nats_connection = await nats.connect(NATS_URL)

        received = []

        async def handler(msg):
            received.append(json.loads(msg.data))

        sub = await nats_connection.subscribe("game.allocated", cb=handler)
        await asyncio.sleep(0.2)

        fake_msg = _FakeMsg(json.dumps({"white_username": "alice", "black_username": "bob"}).encode("utf-8"))
        await _handle_match_found(redis_client, nats_connection, "shard-under-test", fake_msg)
        await asyncio.sleep(0.3)

        await sub.unsubscribe()
        await nats_connection.close()
        return received, redis_client

    received, redis_client = asyncio.run(scenario())

    assert len(received) == 1
    event = received[0]
    assert event["room_id"] is None
    assert event["white_username"] == "alice"
    assert event["black_username"] == "bob"
    assert event["game_id"].startswith("play-")
    assert event["shard_address"] == "shard-under-test"

    assert redis_client.get(f"kfchess:game:{event['game_id']}:owner") == "shard-under-test"


def test_match_found_with_no_live_shard_is_logged_and_not_allocated():
    import nats
    import redis as redis_lib

    from services.game_allocator.main import _handle_match_found

    async def scenario():
        redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        nats_connection = await nats.connect(NATS_URL)

        received = []

        async def handler(msg):
            received.append(json.loads(msg.data))

        sub = await nats_connection.subscribe("game.allocated", cb=handler)
        await asyncio.sleep(0.2)

        fake_msg = _FakeMsg(json.dumps({"white_username": "carol", "black_username": "dave"}).encode("utf-8"))
        await _handle_match_found(redis_client, nats_connection, None, fake_msg)
        await asyncio.sleep(0.3)

        await sub.unsubscribe()
        await nats_connection.close()
        return received

    received = asyncio.run(scenario())

    assert received == []


def test_a_game_id_whose_lease_is_already_held_is_not_reallocated():
    import redis as redis_lib

    from services.game_allocator.main import _acquire_lease

    redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.delete("kfchess:game:already-held:owner")

    assert _acquire_lease(redis_client, "already-held", "shard-a") is True
    assert _acquire_lease(redis_client, "already-held", "shard-b") is False
    assert redis_client.get("kfchess:game:already-held:owner") == "shard-a"


# Mirrors test_match_found_is_allocated_with_a_real_lease above, for the
# room-flow's own equivalent event (services/api_gateway/main.py's
# handle_join_room) - the one difference under test: game_id *is* the
# room_id, not a freshly minted "play-<hex>" id.
def test_room_opponent_joined_is_allocated_with_the_room_id_as_its_own_lease_key():
    import nats
    import redis as redis_lib

    from services.game_allocator.main import _handle_room_opponent_joined

    async def scenario():
        redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.delete("kfchess:game:room-under-test:owner")
        nats_connection = await nats.connect(NATS_URL)

        received = []

        async def handler(msg):
            received.append(json.loads(msg.data))

        sub = await nats_connection.subscribe("game.allocated", cb=handler)
        await asyncio.sleep(0.2)

        payload = {"room_id": "room-under-test", "creator": "alice", "opponent": "bob"}
        fake_msg = _FakeMsg(json.dumps(payload).encode("utf-8"))
        await _handle_room_opponent_joined(redis_client, nats_connection, "shard-under-test", fake_msg)
        await asyncio.sleep(0.3)

        await sub.unsubscribe()
        await nats_connection.close()
        return received, redis_client

    received, redis_client = asyncio.run(scenario())

    assert len(received) == 1
    event = received[0]
    assert event["game_id"] == "room-under-test"
    assert event["room_id"] == "room-under-test"
    assert event["white_username"] == "alice"
    assert event["black_username"] == "bob"
    assert event["shard_address"] == "shard-under-test"

    assert redis_client.get("kfchess:game:room-under-test:owner") == "shard-under-test"


def test_room_opponent_joined_with_no_live_shard_is_logged_and_not_allocated():
    import nats
    import redis as redis_lib

    from services.game_allocator.main import _handle_room_opponent_joined

    async def scenario():
        redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        nats_connection = await nats.connect(NATS_URL)

        received = []

        async def handler(msg):
            received.append(json.loads(msg.data))

        sub = await nats_connection.subscribe("game.allocated", cb=handler)
        await asyncio.sleep(0.2)

        payload = {"room_id": "room-no-shard", "creator": "alice", "opponent": "bob"}
        fake_msg = _FakeMsg(json.dumps(payload).encode("utf-8"))
        await _handle_room_opponent_joined(redis_client, nats_connection, None, fake_msg)
        await asyncio.sleep(0.3)

        await sub.unsubscribe()
        await nats_connection.close()
        return received

    received = asyncio.run(scenario())

    assert received == []
