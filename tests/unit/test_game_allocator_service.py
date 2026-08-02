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

    from server.redis.room_shard_index import RoomShardIndex
    from services.game_allocator.main import _handle_match_found

    async def scenario():
        redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        room_shard_index = RoomShardIndex(REDIS_URL)
        nats_connection = await nats.connect(NATS_URL)

        received = []

        async def handler(msg):
            received.append(json.loads(msg.data))

        sub = await nats_connection.subscribe("game.allocated", cb=handler)
        await asyncio.sleep(0.2)

        fake_msg = _FakeMsg(json.dumps({"white_username": "alice", "black_username": "bob"}).encode("utf-8"))
        await _handle_match_found(redis_client, nats_connection, room_shard_index, "shard-under-test", fake_msg)
        await asyncio.sleep(0.3)

        await sub.unsubscribe()
        await nats_connection.close()
        return received, redis_client, room_shard_index

    received, redis_client, room_shard_index = asyncio.run(scenario())

    assert len(received) == 1
    event = received[0]
    assert event["room_id"] is None
    assert event["white_username"] == "alice"
    assert event["black_username"] == "bob"
    assert event["game_id"].startswith("play-")
    assert event["shard_address"] == "shard-under-test"

    assert redis_client.get(f"kfchess:game:{event['game_id']}:owner") == "shard-under-test"
    # A PLAY match has no room_id - nothing for a spectator to ever look up,
    # so RoomShardIndex has no entry keyed by this game_id at all.
    assert room_shard_index.get(event["game_id"]) is None


def test_match_found_with_no_live_shard_is_logged_and_not_allocated():
    import nats
    import redis as redis_lib

    from server.redis.room_shard_index import RoomShardIndex
    from services.game_allocator.main import _handle_match_found

    async def scenario():
        redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        room_shard_index = RoomShardIndex(REDIS_URL)
        nats_connection = await nats.connect(NATS_URL)

        received = []

        async def handler(msg):
            received.append(json.loads(msg.data))

        sub = await nats_connection.subscribe("game.allocated", cb=handler)
        await asyncio.sleep(0.2)

        fake_msg = _FakeMsg(json.dumps({"white_username": "carol", "black_username": "dave"}).encode("utf-8"))
        await _handle_match_found(redis_client, nats_connection, room_shard_index, None, fake_msg)
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

    from server.redis.room_shard_index import RoomShardIndex
    from services.game_allocator.main import _handle_room_opponent_joined

    async def scenario():
        redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.delete("kfchess:game:room-under-test:owner")
        room_shard_index = RoomShardIndex(REDIS_URL)
        nats_connection = await nats.connect(NATS_URL)

        received = []

        async def handler(msg):
            received.append(json.loads(msg.data))

        sub = await nats_connection.subscribe("game.allocated", cb=handler)
        await asyncio.sleep(0.2)

        payload = {"room_id": "room-under-test", "creator": "alice", "opponent": "bob"}
        fake_msg = _FakeMsg(json.dumps(payload).encode("utf-8"))
        await _handle_room_opponent_joined(redis_client, nats_connection, room_shard_index, "shard-under-test", fake_msg)
        await asyncio.sleep(0.3)

        await sub.unsubscribe()
        await nats_connection.close()
        return received, redis_client, room_shard_index

    received, redis_client, room_shard_index = asyncio.run(scenario())

    assert len(received) == 1
    event = received[0]
    assert event["game_id"] == "room-under-test"
    assert event["room_id"] == "room-under-test"
    assert event["white_username"] == "alice"
    assert event["black_username"] == "bob"
    assert event["shard_address"] == "shard-under-test"

    assert redis_client.get("kfchess:game:room-under-test:owner") == "shard-under-test"
    # The §4 room_id -> worker mapping itself - what a spectator joining
    # this room later resolves through (see services/ws_gateway/main.py's
    # _resolve_shard), with no allocation event of their own to wait on.
    assert room_shard_index.get("room-under-test") == "shard-under-test"


def test_room_opponent_joined_with_no_live_shard_is_logged_and_not_allocated():
    import nats
    import redis as redis_lib

    from server.redis.room_shard_index import RoomShardIndex
    from services.game_allocator.main import _handle_room_opponent_joined

    async def scenario():
        redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        room_shard_index = RoomShardIndex(REDIS_URL)
        nats_connection = await nats.connect(NATS_URL)

        received = []

        async def handler(msg):
            received.append(json.loads(msg.data))

        sub = await nats_connection.subscribe("game.allocated", cb=handler)
        await asyncio.sleep(0.2)

        payload = {"room_id": "room-no-shard", "creator": "alice", "opponent": "bob"}
        fake_msg = _FakeMsg(json.dumps(payload).encode("utf-8"))
        await _handle_room_opponent_joined(redis_client, nats_connection, room_shard_index, None, fake_msg)
        await asyncio.sleep(0.3)

        await sub.unsubscribe()
        await nats_connection.close()
        return received

    received = asyncio.run(scenario())

    assert received == []


# ---- recovery sweep (Server_Design.md §9's own crash story, this module's
# own choice of "where" - see its own docstring) ----


def _sweep_dependencies():
    import redis as redis_lib

    from server.redis.active_game_index import ActiveGameIndex
    from server.redis.busy_set import BusySet
    from server.redis.fairness_checkpoint import FairnessCheckpoint
    from server.redis.room_shard_index import RoomShardIndex
    from server.redis.rooms import RedisRoomRegistry
    from server.redis.shard_registry import ShardRegistry

    redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    busy_set = BusySet(REDIS_URL)
    return {
        "redis_client": redis_client,
        "registry": ShardRegistry(REDIS_URL),
        "room_shard_index": RoomShardIndex(REDIS_URL),
        "rooms": RedisRoomRegistry(REDIS_URL, busy_set=busy_set),
        "active_game_index": ActiveGameIndex(REDIS_URL),
        "fairness_checkpoint": FairnessCheckpoint(REDIS_URL),
        "busy_set": busy_set,
    }


def test_recovery_sweep_voids_a_room_whose_shard_is_no_longer_live():
    from model.piece import BLACK, WHITE
    from server.interfaces import ActiveGameLocation
    from services.game_allocator.main import _sweep_for_dead_shards

    deps = _sweep_dependencies()
    room = deps["rooms"].create("gwa_sweep_creator")
    deps["rooms"].join(room.room_id, "gwa_sweep_opponent")
    deps["room_shard_index"].set(room.room_id, "dead-shard")
    deps["active_game_index"].set(
        "gwa_sweep_creator", ActiveGameLocation(game_id=room.room_id, room_id=room.room_id, seat=WHITE, shard_address="dead-shard")
    )
    deps["active_game_index"].set(
        "gwa_sweep_opponent", ActiveGameLocation(game_id=room.room_id, room_id=room.room_id, seat=BLACK, shard_address="dead-shard")
    )
    # No ShardRegistry.register("dead-shard") at all - it's simply not live.

    asyncio.run(
        _sweep_for_dead_shards(
            deps["registry"],
            deps["room_shard_index"],
            deps["rooms"],
            deps["active_game_index"],
            deps["fairness_checkpoint"],
            deps["busy_set"],
        )
    )

    assert deps["rooms"].room_for_id(room.room_id) is None
    assert deps["active_game_index"].get("gwa_sweep_creator") is None
    assert deps["active_game_index"].get("gwa_sweep_opponent") is None
    assert deps["room_shard_index"].get(room.room_id) is None
    assert not deps["busy_set"].contains("gwa_sweep_creator")
    assert not deps["busy_set"].contains("gwa_sweep_opponent")


def test_recovery_sweep_leaves_a_room_whose_shard_is_still_live():
    from services.game_allocator.main import _sweep_for_dead_shards

    deps = _sweep_dependencies()
    room = deps["rooms"].create("gwa_sweep_alive_creator")
    deps["rooms"].join(room.room_id, "gwa_sweep_alive_opponent")
    deps["room_shard_index"].set(room.room_id, "alive-shard")
    deps["registry"].register("alive-shard")

    try:
        asyncio.run(
            _sweep_for_dead_shards(
                deps["registry"],
                deps["room_shard_index"],
                deps["rooms"],
                deps["active_game_index"],
                deps["fairness_checkpoint"],
                deps["busy_set"],
            )
        )

        assert deps["rooms"].room_for_id(room.room_id) is not None
        assert deps["room_shard_index"].get(room.room_id) == "alive-shard"
    finally:
        # Unlike the "dead shard" tests above, the sweep under test
        # deliberately leaves this room alone (its shard is still live), so
        # nothing cleans it up on our behalf - room.join() already persist()s
        # its owner keys with no TTL once it starts (RedisRoomRegistry's own
        # docstring), so a leaked room here silently outlives this test run
        # and fails the *next* one (`create` raising ALREADY_IN_A_ROOM for
        # gwa_sweep_alive_creator) rather than this one.
        deps["rooms"].close(room.room_id)
        deps["room_shard_index"].remove(room.room_id)


# A PLAY match has no RoomShardIndex entry at all (room_id is None - see
# that class's own docstring), so it's only discoverable through
# ActiveGameIndex - this proves the sweep's second pass actually covers it,
# not just the room-based path every other test above exercises.
def test_recovery_sweep_voids_a_play_match_whose_shard_is_no_longer_live():
    from model.piece import BLACK, WHITE
    from server.interfaces import ActiveGameLocation
    from services.game_allocator.main import _sweep_for_dead_shards

    deps = _sweep_dependencies()
    deps["busy_set"].add("gwa_sweep_play_white")
    deps["busy_set"].add("gwa_sweep_play_black")
    deps["active_game_index"].set(
        "gwa_sweep_play_white",
        ActiveGameLocation(game_id="play-dead", room_id=None, seat=WHITE, shard_address="dead-shard"),
    )
    deps["active_game_index"].set(
        "gwa_sweep_play_black",
        ActiveGameLocation(game_id="play-dead", room_id=None, seat=BLACK, shard_address="dead-shard"),
    )
    # No ShardRegistry.register("dead-shard") at all - it's simply not live.

    asyncio.run(
        _sweep_for_dead_shards(
            deps["registry"],
            deps["room_shard_index"],
            deps["rooms"],
            deps["active_game_index"],
            deps["fairness_checkpoint"],
            deps["busy_set"],
        )
    )

    assert deps["active_game_index"].get("gwa_sweep_play_white") is None
    assert deps["active_game_index"].get("gwa_sweep_play_black") is None
    assert not deps["busy_set"].contains("gwa_sweep_play_white")
    assert not deps["busy_set"].contains("gwa_sweep_play_black")


def test_recovery_sweep_leaves_a_play_match_whose_shard_is_still_live():
    from model.piece import BLACK, WHITE
    from server.interfaces import ActiveGameLocation
    from services.game_allocator.main import _sweep_for_dead_shards

    deps = _sweep_dependencies()
    deps["registry"].register("alive-shard-play")
    deps["active_game_index"].set(
        "gwa_sweep_play_alive_white",
        ActiveGameLocation(game_id="play-alive", room_id=None, seat=WHITE, shard_address="alive-shard-play"),
    )
    deps["active_game_index"].set(
        "gwa_sweep_play_alive_black",
        ActiveGameLocation(game_id="play-alive", room_id=None, seat=BLACK, shard_address="alive-shard-play"),
    )

    asyncio.run(
        _sweep_for_dead_shards(
            deps["registry"],
            deps["room_shard_index"],
            deps["rooms"],
            deps["active_game_index"],
            deps["fairness_checkpoint"],
            deps["busy_set"],
        )
    )

    assert deps["active_game_index"].get("gwa_sweep_play_alive_white") is not None
    assert deps["active_game_index"].get("gwa_sweep_play_alive_black") is not None
