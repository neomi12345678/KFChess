"""Real Redis, no mocks - server/redis/active_game_index.py's
ActiveGameIndex, the standalone API Gateway's POST /login logic
(services/api_gateway/main.py) for answering "is this a reconnect, and to
which color".

Skipped unless KFCHESS_TEST_REDIS_URL is set:

    docker compose up -d redis
    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 python -m pytest tests/unit/test_active_game_index.py

so the default `python -m pytest` stays infra-free.
"""

import os

import pytest

from server.interfaces import ActiveGameLocation

REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(REDIS_URL is None, reason="set KFCHESS_TEST_REDIS_URL to run these")


@pytest.fixture
def index():
    from server.redis.active_game_index import _KEY_PREFIX, ActiveGameIndex

    import redis as redis_lib

    redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    for key in redis_client.scan_iter(match=f"{_KEY_PREFIX}*"):
        redis_client.delete(key)

    return ActiveGameIndex(REDIS_URL)


def test_get_returns_none_for_a_username_with_no_active_game(index):
    assert index.get("nobody") is None


def test_set_then_get_returns_the_same_location(index):
    location = ActiveGameLocation(game_id="play-1", room_id=None, seat="white")

    index.set("alice", location)

    assert index.get("alice") == location


def test_set_for_a_room_game_carries_its_room_id(index):
    location = ActiveGameLocation(game_id="room-abc123", room_id="abc123", seat="black")

    index.set("bob", location)

    assert index.get("bob") == location


def test_remove_clears_the_entry(index):
    index.set("alice", ActiveGameLocation(game_id="play-1", room_id=None, seat="white"))

    index.remove("alice")

    assert index.get("alice") is None


def test_remove_on_an_absent_username_is_a_no_op(index):
    index.remove("nobody")  # must not raise
