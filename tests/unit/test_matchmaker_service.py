"""Real Redis + real NATS, no mocks - the standalone Matchmaker service
(services/matchmaker/main.py) is a thin loop around server/redis/matchmaking.py's
RedisMatchmakingQueue (already covered by tests/unit/test_matchmaking_queue.py)
plus publishing three NATS events instead of calling
ConnectionRegistry.send_to_username directly. This file proves the loop
itself - one tick's worth of advance_time/find_match wired to real
publishes - not the queue semantics again.

Skipped unless both KFCHESS_TEST_REDIS_URL and KFCHESS_TEST_NATS_URL are
set - `docker compose up -d redis nats` then

    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 \
    KFCHESS_TEST_NATS_URL=nats://localhost:4222 \
        python -m pytest tests/unit/test_matchmaker_service.py

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


@pytest.fixture
def queue():
    import redis as redis_lib

    from server.redis.matchmaking import RedisMatchmakingQueue

    redis_lib.Redis.from_url(REDIS_URL).delete("kfchess:matchmaking:by_rating", "kfchess:matchmaking:waiting")
    # Short knobs so the test doesn't take real minutes - this queue's
    # timeout/status-interval are its own construction args, unrelated to
    # the shared production defaults.
    return RedisMatchmakingQueue(REDIS_URL, timeout_ms=1500, status_interval_ms=500)


async def _collect(subject: str, nats_connection, count: int, timeout: float = 3.0):
    received = []
    done = asyncio.Event()

    async def handler(msg):
        received.append(json.loads(msg.data))
        if len(received) >= count:
            done.set()

    sub = await nats_connection.subscribe(subject, cb=handler)
    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    await sub.unsubscribe()
    return received


def test_a_compatible_pair_publishes_match_found(queue):
    import nats

    from services.matchmaker.main import _run_forever

    queue.enqueue("alice", 1200)
    queue.enqueue("bob", 1250)

    async def scenario():
        nats_connection = await nats.connect(NATS_URL)
        task = asyncio.create_task(_run_forever(queue, nats_connection, tick_interval_s=0.05))
        try:
            events = await _collect("match.found", nats_connection, count=1)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await nats_connection.close()
        return events

    events = asyncio.run(scenario())
    assert events == [{"white_username": "alice", "black_username": "bob"}]
    assert queue.is_waiting("alice") is False
    assert queue.is_waiting("bob") is False


def test_on_matchmaking_requested_enqueues_into_the_real_queue():
    import asyncio as _asyncio

    from services.matchmaker.main import _on_matchmaking_requested

    class _FakeMsg:
        def __init__(self, data: bytes):
            self.data = data

    import redis as redis_lib

    from server.redis.matchmaking import RedisMatchmakingQueue

    redis_lib.Redis.from_url(REDIS_URL).delete("kfchess:matchmaking:by_rating", "kfchess:matchmaking:waiting")
    test_queue = RedisMatchmakingQueue(REDIS_URL, timeout_ms=1500, status_interval_ms=500)

    msg = _FakeMsg(json.dumps({"username": "dana", "rating": 1300}).encode("utf-8"))
    _asyncio.run(_on_matchmaking_requested(test_queue, msg))

    assert test_queue.is_waiting("dana") is True


def test_a_lone_waiter_gets_a_status_heartbeat_then_times_out(queue):
    import nats

    from services.matchmaker.main import _run_forever

    queue.enqueue("carol", 1200)

    async def scenario():
        nats_connection = await nats.connect(NATS_URL)
        task = asyncio.create_task(_run_forever(queue, nats_connection, tick_interval_s=0.05))
        try:
            status_events = await _collect("matchmaking.status", nats_connection, count=1)
            timeout_events = await _collect("matchmaking.timeout", nats_connection, count=1, timeout=2.0)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await nats_connection.close()
        return status_events, timeout_events

    status_events, timeout_events = asyncio.run(scenario())
    assert status_events == [{"username": "carol", "seconds_remaining": 1}]
    assert timeout_events == [{"username": "carol"}]
    assert queue.is_waiting("carol") is False
