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

from server.accounts import issue_session_token

DATABASE_URL = os.environ.get("KFCHESS_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")
NATS_URL = os.environ.get("KFCHESS_TEST_NATS_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None or REDIS_URL is None or NATS_URL is None,
    reason="set KFCHESS_TEST_DATABASE_URL, KFCHESS_TEST_REDIS_URL, and KFCHESS_TEST_NATS_URL to run these",
)

# Fixed rather than random - running_app's own monkeypatch.setenv makes this
# the real secret build_app() reads, so any test can sign a token for a
# username it never actually POSTed /login for (most of these seed Redis/
# Postgres state directly rather than going through a real login - see
# individual fixtures below).
_TEST_SESSION_SECRET = b"test-only-session-token-secret"


def _token_for(username: str) -> str:
    return issue_session_token(username, _TEST_SESSION_SECRET, ttl_s=3600)


# A successful /login response now carries a real session token (see
# server/accounts.py's issue_session_token) - stripped here so tests
# asserting the rest of the response's exact shape don't have to hardcode
# an unpredictable value.
def _strip_token(body: dict) -> dict:
    return {key: value for key, value in body.items() if key != "token"}


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
    monkeypatch.setenv("SESSION_TOKEN_SECRET", _TEST_SESSION_SECRET.decode("utf-8"))

    redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.delete("kfchess:busy_usernames")
    redis_client.delete("kfchess:matchmaking:by_rating", "kfchess:matchmaking:waiting")
    # Active-game entries are dynamic (kfchess:active_game:{username}) -
    # wiped by prefix scan rather than by name, same approach
    # tests/unit/test_active_game_index.py's own fixture uses.
    for key in redis_client.scan_iter(match="kfchess:active_game:*"):
        redis_client.delete(key)
    # Room keys are dynamic (kfchess:room:{room_id}) - wiped by prefix scan
    # rather than by name, same approach test_redis_room_registry.py's own
    # fixture uses, so a rerun never trips "already_in_a_room" on a room
    # left over from a previous run.
    for prefix in ("kfchess:room:", "kfchess:room_owner:"):
        for key in redis_client.scan_iter(match=f"{prefix}*"):
            redis_client.delete(key)

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


def _post_json(port: int, path: str, body: dict) -> dict:
    import json
    import urllib.request

    request = urllib.request.Request(
        f"http://localhost:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5.0) as response:
        return json.loads(response.read())


def _get(port: int, path: str):
    import urllib.request

    request = urllib.request.Request(f"http://localhost:{port}{path}", method="GET")
    with urllib.request.urlopen(request, timeout=5.0) as response:
        return response.status, response.getheader("Content-Type"), response.read()


def _post_login(port: int, username: str, password: str) -> dict:
    return _post_json(port, "/login", {"username": username, "password": password})


def _post_play(port: int, username: str) -> dict:
    return _post_json(port, "/play", {"username": username, "token": _token_for(username)})


# Real aiohttp Response construction via a genuinely running server (this
# fixture's own AppRunner/TCPSite) is what actually caught a real bug here
# during manual docker-compose verification: aiohttp's own web.Response
# rejects a content_type string that already carries a charset (which
# prometheus_client's own CONTENT_TYPE_LATEST does) - calling handle_metrics
# as a plain coroutine with a fake request (as a unit test would) never
# constructs a real Response object, so it never would have caught this.
def test_healthz_readyz_and_metrics_are_real_working_routes(running_app):
    import json as json_module

    port, _redis_client = running_app

    health_status, _health_content_type, health_body = _get(port, "/healthz")
    assert health_status == 200
    assert health_body == b"ok"

    ready_status, _ready_content_type, ready_body = _get(port, "/readyz")
    assert ready_status == 200
    assert json_module.loads(ready_body) == {"redis": True, "postgres": True, "nats": True}

    # A real request first, so the request-rate counter has at least one
    # labeled observation to report - a Counter with no observations at all
    # emits nothing in Prometheus text format, by design.
    _post_login(port, "gw_test_alice", "pw12345")

    metrics_status, metrics_content_type, metrics_body = _get(port, "/metrics")
    assert metrics_status == 200
    assert metrics_content_type.startswith("text/plain")
    assert b"kfchess_api_requests_total" in metrics_body


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


def test_a_first_time_username_is_registered_and_logged_in(running_app):
    port, _redis_client = running_app

    body = _post_login(port, "gw_test_new_user", "pw12345")

    assert body["accepted"] is True
    assert body["username"] == "gw_test_new_user"
    assert body["rating"] == 1200
    assert "reconnected" not in body


def test_a_returning_username_with_the_wrong_password_is_rejected(running_app):
    port, _redis_client = running_app

    body = _post_login(port, "gw_test_alice", "wrong-password")

    assert body == {"accepted": False, "reason": "wrong_password"}


# GET /presence/{username} answers "is this username online" for anyone
# who asks - but only a currently-logged-in caller, proven by their own
# session token, not an unauthenticated probe of an arbitrary username
# (see services/api_gateway/main.py's own handle_presence docstring on why
# the token is checked against ?requester=, never against the username in
# the path itself).
def test_presence_without_a_valid_token_is_rejected(running_app):
    import urllib.error

    port, _redis_client = running_app

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(port, "/presence/gw_test_alice")

    assert exc_info.value.code == 401


def test_presence_with_a_valid_token_reports_online_status(running_app):
    import json as json_module

    port, _redis_client = running_app

    login_body = _post_login(port, "gw_test_alice", "pw12345")
    token = login_body["token"]

    status, _content_type, body = _get(port, f"/presence/gw_test_alice?requester=gw_test_alice&token={token}")

    assert status == 200
    assert json_module.loads(body) == {"username": "gw_test_alice", "online": False}


def test_a_username_with_an_active_game_is_reported_as_reconnected(running_app):
    from server.interfaces import ActiveGameLocation
    from server.postgres.accounts import PostgresRatingStore, open_postgres_accounts_database
    from server.redis.active_game_index import ActiveGameIndex

    port, _redis_client = running_app

    ActiveGameIndex(REDIS_URL).set(
        "gw_test_alice", ActiveGameLocation(game_id="play-1", room_id=None, seat="white", shard_address="shard-a")
    )
    # Not assumed to be 1200 - gw_test_alice's account persists in this
    # real (non-:memory:) Postgres database across test runs, so her
    # actual current rating (fetched independently here) is what /login
    # must echo back, not a hardcoded starting value.
    rating = PostgresRatingStore(open_postgres_accounts_database(DATABASE_URL)).rating_for("gw_test_alice")

    body = _post_login(port, "gw_test_alice", "pw12345")

    assert _strip_token(body) == {
        "accepted": True,
        "username": "gw_test_alice",
        "rating": rating,
        "reconnected": True,
        "color": "white",
    }


def test_creating_a_room_returns_a_room_id(running_app):
    port, redis_client = running_app

    body = _post_json(port, "/rooms", {"username": "gw_test_room_creator", "token": _token_for("gw_test_room_creator")})

    assert body["accepted"] is True
    assert body["room_id"]
    assert redis_client.get("kfchess:room_owner:gw_test_room_creator") == body["room_id"]


def test_joining_a_room_seats_the_opponent_and_publishes_room_opponent_joined(running_app):
    import nats

    port, _redis_client = running_app

    created = _post_json(port, "/rooms", {"username": "gw_test_room_alice", "token": _token_for("gw_test_room_alice")})
    room_id = created["room_id"]

    async def scenario():
        nats_connection = await nats.connect(NATS_URL)
        received = []

        async def handler(msg):
            import json

            received.append(json.loads(msg.data))

        sub = await nats_connection.subscribe("room.opponent_joined", cb=handler)
        await asyncio.sleep(0.2)

        loop = asyncio.get_event_loop()
        join_body = await loop.run_in_executor(
            None,
            _post_json,
            port,
            f"/rooms/{room_id}/join",
            {"username": "gw_test_room_bob", "token": _token_for("gw_test_room_bob")},
        )
        await asyncio.sleep(0.3)

        await sub.unsubscribe()
        await nats_connection.close()
        return join_body, received

    join_body, received = asyncio.run(scenario())

    assert join_body == {"accepted": True, "room_id": room_id, "role": "opponent"}
    assert len(received) == 1
    assert received[0] == {"room_id": room_id, "creator": "gw_test_room_alice", "opponent": "gw_test_room_bob"}


def test_joining_a_room_that_already_has_an_opponent_makes_a_spectator(running_app):
    port, _redis_client = running_app

    created = _post_json(
        port, "/rooms", {"username": "gw_test_room_spec_creator", "token": _token_for("gw_test_room_spec_creator")}
    )
    room_id = created["room_id"]
    _post_json(
        port,
        f"/rooms/{room_id}/join",
        {"username": "gw_test_room_spec_opponent", "token": _token_for("gw_test_room_spec_opponent")},
    )

    body = _post_json(
        port,
        f"/rooms/{room_id}/join",
        {"username": "gw_test_room_spec_watcher", "token": _token_for("gw_test_room_spec_watcher")},
    )

    assert body == {"accepted": True, "room_id": room_id, "role": "spectator"}


def test_cancelling_a_pending_room(running_app):
    port, redis_client = running_app

    created = _post_json(
        port, "/rooms", {"username": "gw_test_room_to_cancel", "token": _token_for("gw_test_room_to_cancel")}
    )

    body = _post_json(
        port, "/rooms/cancel", {"username": "gw_test_room_to_cancel", "token": _token_for("gw_test_room_to_cancel")}
    )

    assert body == {"accepted": True}
    assert redis_client.get("kfchess:room_owner:gw_test_room_to_cancel") is None
    assert not redis_client.exists(f"kfchess:room:{created['room_id']}")


# Proves the busy_set integration server/redis/rooms.py's own docstring
# calls out as required, not optional - without RedisRoomRegistry.create
# adding to busy_set, this same username could also queue for PLAY.
def test_a_user_who_created_a_room_cannot_also_play(running_app):
    port, _redis_client = running_app

    _post_json(port, "/rooms", {"username": "gw_test_room_then_play", "token": _token_for("gw_test_room_then_play")})

    body = _post_play(port, "gw_test_room_then_play")

    assert body == {"accepted": False, "reason": "already_in_game"}


# Proves the other half of server/redis/rooms.py's own docstring: a
# game.finished event (the same one services/persistence_worker/main.py
# consumes) must clean up this service's own Redis room state, since
# GameLoop itself only ever closes its own separate, in-process
# RoomRegistry - never this one. Also covers the §4 room_id -> shard_address
# mapping (server/redis/room_shard_index.py's RoomShardIndex) - normally
# written by services/game_allocator/main.py's own _allocate, which isn't
# running in this test, so it's seeded directly here to prove _on_game_finished
# itself removes it.
def test_publishing_game_finished_cleans_up_the_rooms_redis_state(running_app):
    import json

    import nats

    from server.redis.room_shard_index import RoomShardIndex

    port, redis_client = running_app

    created = _post_json(
        port, "/rooms", {"username": "gw_test_room_finish_creator", "token": _token_for("gw_test_room_finish_creator")}
    )
    room_id = created["room_id"]
    _post_json(
        port,
        f"/rooms/{room_id}/join",
        {"username": "gw_test_room_finish_opponent", "token": _token_for("gw_test_room_finish_opponent")},
    )

    room_shard_index = RoomShardIndex(REDIS_URL)
    room_shard_index.set(room_id, "shard-under-test")

    async def publish_game_finished():
        nats_connection = await nats.connect(NATS_URL)
        payload = {
            "game_id": room_id,
            "room_id": room_id,
            "white_username": "gw_test_room_finish_creator",
            "black_username": "gw_test_room_finish_opponent",
            "ratings": {"white": 1200, "black": 1200},
        }
        await nats_connection.publish("game.finished", json.dumps(payload).encode("utf-8"))
        await nats_connection.flush()
        await nats_connection.close()

    asyncio.run(publish_game_finished())

    assert _wait_until(lambda: not redis_client.exists(f"kfchess:room:{room_id}"))
    assert _wait_until(lambda: redis_client.get("kfchess:room_owner:gw_test_room_finish_creator") is None)
    assert not redis_client.sismember("kfchess:busy_usernames", "gw_test_room_finish_creator")
    assert not redis_client.sismember("kfchess:busy_usernames", "gw_test_room_finish_opponent")
    assert _wait_until(lambda: room_shard_index.get(room_id) is None)
