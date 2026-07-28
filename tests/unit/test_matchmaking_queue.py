"""Same behavioral test suite run against both server/matchmaking.py's
MatchmakingQueue and server/redis/matchmaking.py's RedisMatchmakingQueue -
mirroring this project's own existing pattern of proving an interface by
running one test suite against two implementations (see
tests/unit/test_board_representation.py, called out in README.md).

The Redis case is real Redis, no mocks (this project's own convention) -
skipped unless KFCHESS_TEST_REDIS_URL points at a reachable Redis:

    docker compose up -d redis
    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 python -m pytest tests/unit/test_matchmaking_queue.py
"""

import os

import pytest

from server.matchmaking import MatchmakingQueue

REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")

# advance_time is pure bookkeeping (no real sleep involved - these ms values
# are just synthetic input to a pure function), so _STATUS_INTERVAL_MS is
# picked to divide _TIMEOUT_MS evenly into a few distinct boundaries (3000,
# 6000, 9000) with clearly different whole-seconds-remaining at each, rather
# than for any actual timing reason.
_TIMEOUT_MS = 10_000
_STATUS_INTERVAL_MS = 3_000


def _in_memory_queue():
    return MatchmakingQueue(timeout_ms=_TIMEOUT_MS, status_interval_ms=_STATUS_INTERVAL_MS)


def _redis_queue():
    import redis as redis_lib

    from server.redis.matchmaking import RedisMatchmakingQueue, _ORDER_KEY, _WAITING_KEY

    # A fresh queue per test - this project's own SQLite fixtures get that
    # for free from ":memory:"; Redis needs an explicit clear instead.
    redis_lib.Redis.from_url(REDIS_URL).delete(_ORDER_KEY, _WAITING_KEY)
    return RedisMatchmakingQueue(REDIS_URL, timeout_ms=_TIMEOUT_MS, status_interval_ms=_STATUS_INTERVAL_MS)


_CASES = [pytest.param(_in_memory_queue, id="in-memory")]
if REDIS_URL:
    _CASES.append(pytest.param(_redis_queue, id="redis"))
else:
    _CASES.append(
        pytest.param(
            _redis_queue,
            id="redis",
            marks=pytest.mark.skip(reason="set KFCHESS_TEST_REDIS_URL to a real Redis to run these"),
        )
    )


@pytest.fixture(params=_CASES)
def queue(request):
    return request.param()


def test_enqueue_then_is_waiting(queue):
    queue.enqueue("alice", 1200)

    assert queue.is_waiting("alice") is True
    assert queue.is_waiting("bob") is False


def test_remove_clears_is_waiting(queue):
    queue.enqueue("alice", 1200)

    queue.remove("alice")

    assert queue.is_waiting("alice") is False


def test_remove_of_a_never_queued_username_is_a_no_op(queue):
    queue.remove("nobody")  # must not raise


def test_find_match_pairs_two_ratings_within_range(queue):
    queue.enqueue("alice", 1200)
    queue.enqueue("bob", 1250)  # within RATING_RANGE (100)

    assert queue.find_match() == ("alice", "bob")


def test_find_match_skips_a_pair_outside_rating_range(queue):
    queue.enqueue("alice", 1200)
    queue.enqueue("bob", 1400)  # outside RATING_RANGE

    assert queue.find_match() is None


def test_find_match_prefers_the_earliest_queued_pair(queue):
    queue.enqueue("alice", 1200)
    queue.enqueue("carol", 1400)  # too far from alice to match
    queue.enqueue("bob", 1250)  # matches alice; carol never matches anyone

    assert queue.find_match() == ("alice", "bob")


def test_find_match_does_not_remove_either_side_of_the_match(queue):
    queue.enqueue("alice", 1200)
    queue.enqueue("bob", 1250)

    queue.find_match()

    assert queue.is_waiting("alice") is True
    assert queue.is_waiting("bob") is True


def test_advance_time_expires_entries_past_timeout(queue):
    queue.enqueue("alice", 1200)

    expired = queue.advance_time(_TIMEOUT_MS + 500).timed_out

    assert expired == ["alice"]
    assert queue.is_waiting("alice") is False


def test_advance_time_does_not_expire_entries_under_timeout(queue):
    queue.enqueue("alice", 1200)

    expired = queue.advance_time(_TIMEOUT_MS - 500).timed_out

    assert expired == []
    assert queue.is_waiting("alice") is True


def test_re_enqueue_resets_waited_ms(queue):
    queue.enqueue("alice", 1200)
    queue.advance_time(_TIMEOUT_MS - 400)  # close to expiring

    queue.enqueue("alice", 1200)  # re-queued - waited_ms resets to 0
    expired = queue.advance_time(_TIMEOUT_MS - 400).timed_out  # would total > timeout without the reset

    assert expired == []
    assert queue.is_waiting("alice") is True


def test_advance_time_reports_nothing_due_before_the_status_interval(queue):
    queue.enqueue("alice", 1200)

    due_for_status = queue.advance_time(_STATUS_INTERVAL_MS - 500).due_for_status

    assert due_for_status == []


def test_advance_time_reports_due_for_status_once_the_interval_is_crossed(queue):
    queue.enqueue("alice", 1200)

    due_for_status = queue.advance_time(_STATUS_INTERVAL_MS).due_for_status

    # 10_000ms timeout - 3_000ms waited = 7_000ms remaining -> 7 whole seconds.
    assert due_for_status == [("alice", 7)]


def test_advance_time_reports_due_for_status_again_on_each_subsequent_interval(queue):
    queue.enqueue("alice", 1200)

    first = queue.advance_time(_STATUS_INTERVAL_MS).due_for_status
    second = queue.advance_time(_STATUS_INTERVAL_MS).due_for_status
    third = queue.advance_time(_STATUS_INTERVAL_MS).due_for_status

    # A rolling per-entry clock, not a one-shot: fires on every boundary
    # crossed, with seconds_remaining shrinking each time.
    assert first == [("alice", 7)]
    assert second == [("alice", 4)]
    assert third == [("alice", 1)]


def test_advance_time_does_not_report_due_for_status_again_before_the_next_interval(queue):
    queue.enqueue("alice", 1200)
    queue.advance_time(_STATUS_INTERVAL_MS)  # first heartbeat fires here

    due_for_status = queue.advance_time(_STATUS_INTERVAL_MS - 500).due_for_status

    assert due_for_status == []


def test_advance_time_reports_only_timed_out_when_a_status_boundary_and_the_timeout_coincide(queue):
    queue.enqueue("alice", 1200)

    tick = queue.advance_time(_TIMEOUT_MS + _STATUS_INTERVAL_MS)

    # alice crosses both a stale notify-boundary and the timeout in the same
    # call - only ever reported as timed out, never a heartbeat one moment
    # before the timeout that follows it.
    assert tick.timed_out == ["alice"]
    assert tick.due_for_status == []


def test_re_enqueue_resets_last_notified_ms(queue):
    queue.enqueue("alice", 1200)
    first = queue.advance_time(_STATUS_INTERVAL_MS).due_for_status  # first heartbeat fires, last_notified_ms -> 3000

    queue.enqueue("alice", 1200)  # re-queued - waited_ms AND last_notified_ms both reset to 0
    # Advancing by exactly one fresh interval only fires again if
    # last_notified_ms actually reset to 0 - a stale last_notified_ms of
    # 3000 left over from before the re-enqueue would make this
    # "waited_ms(3000) - last_notified_ms(3000) >= interval" false instead.
    second = queue.advance_time(_STATUS_INTERVAL_MS).due_for_status

    assert first == [("alice", 7)]
    assert second == [("alice", 7)]
