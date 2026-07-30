"""Real Redis, no mocks - server/redis/presence.py's Presence, the
Server_Design.md §5 "Presence / session directory | Redis | Low latency,
doesn't need durability beyond a TTL."

Skipped unless KFCHESS_TEST_REDIS_URL is set:

    docker compose up -d redis
    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 python -m pytest tests/unit/test_presence.py
"""

import os

import pytest

REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(REDIS_URL is None, reason="set KFCHESS_TEST_REDIS_URL to run these")


@pytest.fixture
def presence():
    from server.redis.presence import _ONLINE_KEY, Presence

    import redis as redis_lib

    redis_lib.Redis.from_url(REDIS_URL).delete(_ONLINE_KEY)
    return Presence(REDIS_URL)


def test_is_online_for_a_never_marked_username_is_false(presence):
    assert presence.is_online("alice") is False


def test_mark_online_then_is_online(presence):
    presence.mark_online("alice")

    assert presence.is_online("alice") is True


def test_mark_offline_clears_it(presence):
    presence.mark_online("alice")

    presence.mark_offline("alice")

    assert presence.is_online("alice") is False


def test_mark_offline_on_a_never_marked_username_is_a_no_op(presence):
    presence.mark_offline("nobody")  # must not raise


def test_mark_online_twice_is_idempotent(presence):
    presence.mark_online("alice")
    presence.mark_online("alice")

    assert presence.online_count() == 1


def test_online_count_reflects_every_currently_online_username(presence):
    presence.mark_online("alice")
    presence.mark_online("bob")

    assert presence.online_count() == 2

    presence.mark_offline("alice")

    assert presence.online_count() == 1
