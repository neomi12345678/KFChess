"""Real Redis, no mocks - server/redis/rooms.py's RedisRoomRegistry, the
standalone API Gateway's room create/join/cancel logic
(services/api_gateway/main.py).

Skipped unless KFCHESS_TEST_REDIS_URL is set:

    docker compose up -d redis
    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 python -m pytest tests/unit/test_redis_room_registry.py

so the default `python -m pytest` stays infra-free.
"""

import os

import pytest

from protocol.types import Reason

REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(REDIS_URL is None, reason="set KFCHESS_TEST_REDIS_URL to run these")


@pytest.fixture
def registry():
    from server.redis.rooms import _ROOM_KEY_PREFIX, _ROOM_OWNER_KEY_PREFIX, RedisRoomRegistry

    import redis as redis_lib

    redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    for prefix in (_ROOM_KEY_PREFIX, _ROOM_OWNER_KEY_PREFIX):
        for key in redis_client.scan_iter(match=f"{prefix}*"):
            redis_client.delete(key)

    return RedisRoomRegistry(REDIS_URL)


def test_create_makes_a_new_pending_room(registry):
    room = registry.create("alice")

    assert room.creator == "alice"
    assert room.opponent is None
    assert room.is_pending
    assert registry.room_for_username("alice").room_id == room.room_id


def test_creating_while_already_in_a_room_is_rejected(registry):
    from server.rooms import RoomError

    registry.create("alice")

    with pytest.raises(RoomError, match=Reason.ALREADY_IN_A_ROOM.value):
        registry.create("alice")


def test_the_first_join_becomes_the_opponent(registry):
    room = registry.create("alice")

    joined = registry.join(room.room_id, "bob")

    assert joined.opponent == "bob"
    assert not joined.is_pending
    assert registry.room_for_username("bob").room_id == room.room_id


def test_a_join_after_the_opponent_seat_is_filled_becomes_a_spectator(registry):
    room = registry.create("alice")
    registry.join(room.room_id, "bob")

    joined = registry.join(room.room_id, "carol")

    assert joined.opponent == "bob"
    assert joined.spectators == {"carol"}
    assert registry.room_for_username("carol").room_id == room.room_id


def test_joining_a_nonexistent_room_is_rejected(registry):
    from server.rooms import RoomError

    with pytest.raises(RoomError, match=Reason.ROOM_NOT_FOUND.value):
        registry.join("no-such-room", "alice")


def test_joining_while_already_in_a_room_is_rejected(registry):
    from server.rooms import RoomError

    room = registry.create("alice")
    registry.create("bob")

    with pytest.raises(RoomError, match=Reason.ALREADY_IN_A_ROOM.value):
        registry.join(room.room_id, "bob")


def test_cancel_removes_a_pending_room(registry):
    room = registry.create("alice")

    registry.cancel("alice")

    assert registry.room_for_username("alice") is None
    from server.rooms import RoomError

    with pytest.raises(RoomError, match=Reason.ROOM_NOT_FOUND.value):
        registry.join(room.room_id, "bob")


def test_cancel_by_a_username_not_in_a_room_is_rejected(registry):
    from server.rooms import RoomError

    with pytest.raises(RoomError, match=Reason.NOT_IN_A_ROOM.value):
        registry.cancel("nobody")


def test_cancel_by_the_opponent_not_the_creator_is_rejected(registry):
    from server.rooms import RoomError

    room = registry.create("alice")
    registry.join(room.room_id, "bob")

    with pytest.raises(RoomError, match=Reason.NOT_THE_CREATOR.value):
        registry.cancel("bob")


def test_cancel_after_the_opponent_joined_is_rejected(registry):
    from server.rooms import RoomError

    room = registry.create("alice")
    registry.join(room.room_id, "bob")

    with pytest.raises(RoomError, match=Reason.ALREADY_STARTED.value):
        registry.cancel("alice")


def test_room_for_username_is_none_when_not_in_a_room(registry):
    assert registry.room_for_username("nobody") is None


@pytest.fixture
def registry_and_busy_set():
    from server.redis.busy_set import BusySet
    from server.redis.rooms import _ROOM_KEY_PREFIX, _ROOM_OWNER_KEY_PREFIX, RedisRoomRegistry

    import redis as redis_lib

    redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.delete("kfchess:busy_usernames")
    for prefix in (_ROOM_KEY_PREFIX, _ROOM_OWNER_KEY_PREFIX):
        for key in redis_client.scan_iter(match=f"{prefix}*"):
            redis_client.delete(key)

    busy_set = BusySet(REDIS_URL)
    return RedisRoomRegistry(REDIS_URL, busy_set=busy_set), busy_set


def test_create_adds_the_creator_to_the_busy_set(registry_and_busy_set):
    registry, busy_set = registry_and_busy_set

    registry.create("alice")

    assert busy_set.contains("alice")


def test_joining_as_the_opponent_adds_to_the_busy_set(registry_and_busy_set):
    registry, busy_set = registry_and_busy_set
    room = registry.create("alice")

    registry.join(room.room_id, "bob")

    assert busy_set.contains("bob")


def test_joining_as_a_spectator_does_not_add_to_the_busy_set(registry_and_busy_set):
    registry, busy_set = registry_and_busy_set
    room = registry.create("alice")
    registry.join(room.room_id, "bob")

    registry.join(room.room_id, "carol")

    assert not busy_set.contains("carol")


def test_cancel_removes_the_creator_from_the_busy_set(registry_and_busy_set):
    registry, busy_set = registry_and_busy_set
    registry.create("alice")

    registry.cancel("alice")

    assert not busy_set.contains("alice")


def test_close_removes_the_room_and_frees_both_participants(registry_and_busy_set):
    registry, busy_set = registry_and_busy_set
    room = registry.create("alice")
    registry.join(room.room_id, "bob")

    registry.close(room.room_id)

    assert registry.room_for_username("alice") is None
    assert registry.room_for_username("bob") is None
    assert not busy_set.contains("alice")
    assert not busy_set.contains("bob")


def test_close_on_an_already_gone_room_is_a_no_op(registry_and_busy_set):
    registry, _busy_set = registry_and_busy_set

    registry.close("no-such-room")  # must not raise
