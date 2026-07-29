"""Real Redis, no mocks - server/redis/shard_registry.py's ShardRegistry,
the Game Server Shard side (register/heartbeat) and the Game Allocator
side (list_live_shards/pick_shard) of the shard-discovery mechanism
described in that module's own docstring.

Skipped unless KFCHESS_TEST_REDIS_URL is set:

    docker compose up -d redis
    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 python -m pytest tests/unit/test_shard_registry.py

so the default `python -m pytest` stays infra-free.
"""

import os
import time

import pytest

REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(REDIS_URL is None, reason="set KFCHESS_TEST_REDIS_URL to run these")


@pytest.fixture
def registry():
    from server.redis.shard_registry import _SHARD_KEY_PREFIX, ShardRegistry

    import redis as redis_lib

    redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    for key in redis_client.scan_iter(match=f"{_SHARD_KEY_PREFIX}*"):
        redis_client.delete(key)

    return ShardRegistry(REDIS_URL)


def test_pick_shard_returns_none_when_no_shard_is_registered(registry):
    assert registry.list_live_shards() == []
    assert registry.pick_shard() is None


def test_register_makes_a_shard_discoverable(registry):
    registry.register("game-server-a")

    assert registry.list_live_shards() == ["game-server-a"]
    assert registry.pick_shard() == "game-server-a"


def test_multiple_registered_shards_all_show_up(registry):
    registry.register("game-server-a")
    registry.register("game-server-b")

    assert set(registry.list_live_shards()) == {"game-server-a", "game-server-b"}
    assert registry.pick_shard() in {"game-server-a", "game-server-b"}


def test_a_registration_expires_after_its_ttl(registry):
    from server.redis.shard_registry import ShardRegistry

    short_lived_registry = ShardRegistry(REDIS_URL, ttl_ms=200)
    short_lived_registry.register("game-server-transient")
    assert short_lived_registry.list_live_shards() == ["game-server-transient"]

    time.sleep(0.4)

    assert short_lived_registry.list_live_shards() == []
    assert short_lived_registry.pick_shard() is None
