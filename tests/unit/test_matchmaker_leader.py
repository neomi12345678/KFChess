"""Real Redis, no mocks - server/redis/matchmaker_leader.py's
MatchmakerLeaderElection, the lease that lets more than one standalone
Matchmaker replica (services/matchmaker/main.py) run safely against the
same shared RedisMatchmakingQueue: only whichever replica holds this lease
actually ticks the queue (see that module's own docstring on why more than
one concurrent ticker double-counts waited_ms and can double-claim a
match).

Skipped unless KFCHESS_TEST_REDIS_URL is set:

    docker compose up -d redis
    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 python -m pytest tests/unit/test_matchmaker_leader.py
"""

import os
import time

import pytest

from server.redis.matchmaker_leader import _LEADER_KEY, MatchmakerLeaderElection

REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(REDIS_URL is None, reason="set KFCHESS_TEST_REDIS_URL to run these")


@pytest.fixture(autouse=True)
def _clean_leader_key():
    import redis as redis_lib

    redis_lib.Redis.from_url(REDIS_URL).delete(_LEADER_KEY)


def test_the_first_instance_to_call_becomes_leader():
    leader = MatchmakerLeaderElection(REDIS_URL, ttl_ms=5000)

    assert leader.acquire_or_renew() is True


def test_a_second_instance_cannot_acquire_while_the_first_is_still_leader():
    first = MatchmakerLeaderElection(REDIS_URL, ttl_ms=5000)
    second = MatchmakerLeaderElection(REDIS_URL, ttl_ms=5000)

    assert first.acquire_or_renew() is True
    assert second.acquire_or_renew() is False


def test_the_leader_can_keep_renewing_its_own_lease():
    leader = MatchmakerLeaderElection(REDIS_URL, ttl_ms=5000)
    leader.acquire_or_renew()

    assert leader.acquire_or_renew() is True
    assert leader.acquire_or_renew() is True


def test_a_new_instance_takes_over_once_the_leaders_lease_expires():
    first = MatchmakerLeaderElection(REDIS_URL, ttl_ms=200)
    second = MatchmakerLeaderElection(REDIS_URL, ttl_ms=5000)
    first.acquire_or_renew()

    time.sleep(0.4)  # past first's own 200ms TTL, with nothing renewing it

    assert second.acquire_or_renew() is True


def test_renewing_before_expiry_keeps_out_a_second_instance():
    # Unlike server/redis/room_shard_index.py's own renew (which takes
    # ttl_ms per call, so a test can renew to a longer window than the
    # initial one), MatchmakerLeaderElection always renews to the same
    # fixed ttl_ms it was constructed with - matching real usage (every
    # tick renews to the same interval). So both sleeps here need to fit
    # comfortably inside one ttl_ms window with margin for real Redis
    # round-trip latency, not just past a shorter original TTL.
    first = MatchmakerLeaderElection(REDIS_URL, ttl_ms=1000)
    second = MatchmakerLeaderElection(REDIS_URL, ttl_ms=1000)
    first.acquire_or_renew()

    time.sleep(0.3)
    assert first.acquire_or_renew() is True  # renews well before the 1000ms window would expire

    time.sleep(0.3)  # 300ms since the renewal - comfortably inside the fresh 1000ms window

    assert second.acquire_or_renew() is False


def test_the_old_leader_cannot_reclaim_after_someone_else_takes_over():
    first = MatchmakerLeaderElection(REDIS_URL, ttl_ms=200)
    second = MatchmakerLeaderElection(REDIS_URL, ttl_ms=5000)
    first.acquire_or_renew()

    time.sleep(0.4)
    second.acquire_or_renew()  # second is now the leader

    # first's own renew script checks its own instance id against what's on
    # file - now second's - so it must fail, not silently resume leadership.
    assert first.acquire_or_renew() is False
