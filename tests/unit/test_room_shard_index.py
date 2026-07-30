"""Real Redis, no mocks - server/redis/room_shard_index.py's RoomShardIndex,
the Server_Design.md §4 room-ownership lease itself (SET ... NX PX,
renewed by heartbeat, released on game-over/crash - see that module's own
docstring).

Skipped unless KFCHESS_TEST_REDIS_URL is set:

    docker compose up -d redis
    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 python -m pytest tests/unit/test_room_shard_index.py
"""

import os

import pytest

REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(REDIS_URL is None, reason="set KFCHESS_TEST_REDIS_URL to run these")


@pytest.fixture
def index():
    from server.redis.room_shard_index import _KEY_PREFIX, RoomShardIndex

    import redis as redis_lib

    redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    for key in redis_client.scan_iter(match=f"{_KEY_PREFIX}*"):
        redis_client.delete(key)

    return RoomShardIndex(REDIS_URL)


def test_get_on_an_unset_room_is_none(index):
    assert index.get("room-1") is None


def test_set_acquires_the_lease(index):
    assert index.set("room-1", "shard-a") is True
    assert index.get("room-1") == "shard-a"


# The literal §4 requirement: "A new worker can only take over once the
# lease has actually expired, never by just overwriting a live entry."
def test_set_on_an_already_held_room_fails_and_does_not_overwrite(index):
    index.set("room-1", "shard-a")

    assert index.set("room-1", "shard-b") is False
    assert index.get("room-1") == "shard-a"


def test_remove_releases_the_lease(index):
    index.set("room-1", "shard-a")

    index.remove("room-1")

    assert index.get("room-1") is None


def test_remove_on_an_absent_room_is_a_no_op(index):
    index.remove("nobody-holds-this")  # must not raise


# The heartbeat - only the current holder can extend its own lease.
def test_renew_by_the_current_holder_succeeds(index):
    index.set("room-1", "shard-a")

    assert index.renew("room-1", "shard-a", ttl_ms=5000) is True
    assert index.get("room-1") == "shard-a"


def test_renew_by_a_non_holder_fails(index):
    index.set("room-1", "shard-a")

    assert index.renew("room-1", "shard-b", ttl_ms=5000) is False
    # Still shard-a's - a failed renew from an impostor must not clobber it.
    assert index.get("room-1") == "shard-a"


def test_renew_on_a_room_with_no_lease_at_all_fails(index):
    assert index.renew("never-set", "shard-a", ttl_ms=5000) is False


def test_renew_actually_extends_the_ttl(index):
    import time

    index.set("room-1", "shard-a", ttl_ms=200)

    time.sleep(0.1)
    assert index.renew("room-1", "shard-a", ttl_ms=5000) is True
    time.sleep(0.2)  # past the *original* 200ms TTL, well inside the renewed one

    assert index.get("room-1") == "shard-a"


def test_a_lease_expires_on_its_own_without_renewal(index):
    import time

    index.set("room-1", "shard-a", ttl_ms=200)

    time.sleep(0.4)

    assert index.get("room-1") is None
    # And a new worker can now legitimately acquire it - the whole point.
    assert index.set("room-1", "shard-b") is True


def test_all_room_ids_lists_every_currently_leased_room(index):
    index.set("room-1", "shard-a")
    index.set("room-2", "shard-b")

    assert set(index.all_room_ids()) == {"room-1", "room-2"}


def test_all_room_ids_excludes_removed_rooms(index):
    index.set("room-1", "shard-a")
    index.set("room-2", "shard-b")

    index.remove("room-1")

    assert index.all_room_ids() == ["room-2"]
