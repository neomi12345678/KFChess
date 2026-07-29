"""Real Postgres + real Redis + real NATS, no mocks - posts to a real
running api_gateway instance (the actual aiohttp app, built via
services.api_gateway.main's own build_app()) and asserts the enqueue actually lands
in kfchess:matchmaking:waiting, the busy-set rejection works, and an
already-queued user is rejected - the same three cases
services/api_gateway/main.py's own docstring describes.

NATS is real here (not stubbed) because handle_play no longer touches
Redis directly - it publishes matchmaking.requested and services/matchmaker/main.py's
own _on_matchmaking_requested is what actually calls queue.enqueue (see
services/api_gateway/main.py's docstring on this). This fixture runs that same
handler against a real NATS subscription, exactly like the real Matchmaker
service would, so the enqueue happens for real rather than being faked
here a second way.

Skipped unless KFCHESS_TEST_DATABASE_URL, KFCHESS_TEST_REDIS_URL, and
KFCHESS_TEST_NATS_URL are all set - `docker compose up -d postgres redis nats` then

    KFCHESS_TEST_DATABASE_URL=postgresql://kfchess:kfchess@localhost:55432/kfchess \
    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 \
    KFCHESS_TEST_NATS_URL=nats://localhost:4222 \
        python -m pytest tests/integration/test_api_gateway.py

so the default `python -m pytest` stays infra-free.
"""

import asyncio
import os
import threading
import time

import pytest

DATABASE_URL = os.environ.get("KFCHESS_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")
NATS_URL = os.environ.get("KFCHESS_TEST_NATS_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None or REDIS_URL is None or NATS_URL is None,
    reason="set KFCHESS_TEST_DATABASE_URL, KFCHESS_TEST_REDIS_URL, and KFCHESS_TEST_NATS_URL to run these",
)


def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def running_app(monkeypatch):
    import redis as redis_lib

    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    monkeypatch.setenv("NATS_URL", NATS_URL)

    redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.delete("kfchess:busy_usernames")
    redis_client.delete("kfchess:matchmaking:order", "kfchess:matchmaking:waiting")

    from server.postgres.accounts import PostgresUserStore, open_postgres_accounts_database

    accounts_database = open_postgres_accounts_database(DATABASE_URL)
    PostgresUserStore(accounts_database).login("gw_test_alice", "pw12345")

    async def start():
        import aiohttp.web
        import nats

        from services.api_gateway.main import build_app
        from services.matchmaker.main import _on_matchmaking_requested
        from server.redis.matchmaking import RedisMatchmakingQueue

        app = build_app()
        runner = aiohttp.web.AppRunner(app)
        await runner.setup()
        site = aiohttp.web.TCPSite(runner, "localhost", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        # A real matchmaking.requested consumer - see this file's own
        # docstring on why the enqueue itself doesn't happen inside the app.
        consumer_queue = RedisMatchmakingQueue(REDIS_URL)
        consumer_connection = await nats.connect(NATS_URL)

        async def _on_message(msg) -> None:
            await _on_matchmaking_requested(consumer_queue, msg)

        sub = await consumer_connection.subscribe("matchmaking.requested", cb=_on_message)
        return runner, port, consumer_connection, sub

    # The test itself makes plain blocking urllib calls (matching the real
    # clients - see client/client_cli.py's own _post_play), so the aiohttp
    # server's event loop needs to keep actually running in the background
    # to accept them, the same way client/network_client.py's own
    # NetworkGameClient runs its websocket loop on a dedicated thread rather
    # than one this test's own (synchronous) body drives itself.
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state = {}

    def _run_loop():
        asyncio.set_event_loop(loop)
        state["runner"], state["port"], state["consumer_connection"], state["sub"] = loop.run_until_complete(start())
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    ready.wait(timeout=5.0)

    yield state["port"], redis_client

    async def _cleanup() -> None:
        await state["sub"].unsubscribe()
        await state["consumer_connection"].close()
        await state["runner"].cleanup()

    asyncio.run_coroutine_threadsafe(_cleanup(), loop).result(timeout=5.0)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5.0)
    loop.close()


def _post_play(port: int, username: str) -> dict:
    import json
    import urllib.request

    request = urllib.request.Request(
        f"http://localhost:{port}/play",
        data=json.dumps({"username": username}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5.0) as response:
        return json.loads(response.read())


def test_a_registered_user_gets_enqueued_into_the_real_shared_queue(running_app):
    port, redis_client = running_app

    body = _post_play(port, "gw_test_alice")

    assert body == {"accepted": True, "reason": "queued"}
    # Async now - handle_play only publishes matchmaking.requested; the
    # actual enqueue happens once the fixture's own consumer processes it.
    assert _wait_until(lambda: redis_client.hexists("kfchess:matchmaking:waiting", "gw_test_alice"))


def test_an_already_queued_user_is_rejected(running_app):
    port, redis_client = running_app

    _post_play(port, "gw_test_alice")
    assert _wait_until(lambda: redis_client.hexists("kfchess:matchmaking:waiting", "gw_test_alice"))

    body = _post_play(port, "gw_test_alice")

    assert body == {"accepted": False, "reason": "already_queued"}


def test_a_busy_user_is_rejected_without_touching_the_queue(running_app):
    port, redis_client = running_app
    redis_client.sadd("kfchess:busy_usernames", "gw_test_busy")

    body = _post_play(port, "gw_test_busy")

    assert body == {"accepted": False, "reason": "already_in_game"}
    assert not redis_client.hexists("kfchess:matchmaking:waiting", "gw_test_busy")
