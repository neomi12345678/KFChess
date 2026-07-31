"""Standalone Matchmaker service - the tick loop server/game_loop.py's
GameLoop used to run in-process (_advance_matchmaking/_try_start_a_match,
now skipped once EXTERNAL_MATCHMAKER=1 is set on the game-server - see
GameLoop.start_matchmaking_relay's own docstring for why the two can't run
at once), pulled out into its own deployable so matchmaking pairing keeps
running independently of any one game-server instance.

Reuses server/redis/matchmaking.py's RedisMatchmakingQueue unchanged - the
same two Redis keys (kfchess:matchmaking:by_rating/kfchess:matchmaking:waiting)
this service manages are exactly what server/router.py's CommandRouter
still writes to directly for the bare-metal websocket PLAY path (that path
is intentionally untouched - see below). This process holds no websocket
of its own, so what the in-process loop used to compute and send directly
via ConnectionRegistry.send_to_username is published as NATS events
instead:

    matchmaking.status  {"username": str, "seconds_remaining": int}
    matchmaking.timeout {"username": str}
    match.found         {"white_username": str, "black_username": str}

game-server subscribes to the first two and forwards them to the right
websocket (see GameLoop.start_matchmaking_relay). A separate Game
Allocator service subscribes to match.found (see
services/game_allocator/main.py).

Subscribes to:
    matchmaking.requested  {"username": str, "rating": int}

published by services/api_gateway/main.py's handle_play - Server_Design.md's own
§6.2 flow ("API Gateway publishes a matchmaking request onto the NATS
control plane. Matchmaker sees every waiting player globally"): this
service, not API Gateway, is what actually calls queue.enqueue. API
Gateway keeps its own busy/already-queued checks and rating lookup
synchronous (needed for an immediate REST response) but no longer touches
the queue directly. server/router.py's own CommandRouter.decide_play (the
bare-metal websocket PLAY path, used when there's no standalone API
Gateway at all) still enqueues directly and is deliberately left alone -
Server_Design.md's flow describes the API-Gateway-fronted deployment
specifically, not that fallback.
"""

import asyncio
import logging
import os

import nats
from prometheus_client import Gauge

from server.logging_config import configure_logging, username_ctx
from server.nats.events import MatchFound, MatchmakingRequested, MatchmakingStatus, MatchmakingTimeout
from server.observability_server import start_observability_server
from server.redis.matchmaker_leader import MatchmakerLeaderElection
from server.redis.matchmaking import RedisMatchmakingQueue
from server.server_config import DEFAULT_TICK_INTERVAL_S

_logger = logging.getLogger(__name__)

# Server_Design.md §9's own "queue depth per Matchmaker replica".
_QUEUE_DEPTH_GAUGE = Gauge("kfchess_matchmaker_queue_depth", "Usernames currently waiting for a PLAY match")


async def _on_matchmaking_requested(queue: RedisMatchmakingQueue, msg) -> None:
    event = MatchmakingRequested.decode(msg.data)
    username_ctx.set(event.username)
    queue.enqueue(event.username, event.rating)


async def _run_forever(
    queue: RedisMatchmakingQueue, nats_connection, tick_interval_s: float, leader: MatchmakerLeaderElection
) -> None:
    last = asyncio.get_event_loop().time()
    while True:
        await asyncio.sleep(tick_interval_s)
        now = asyncio.get_event_loop().time()
        elapsed_ms = int((now - last) * 1000)
        last = now

        # A transient Redis blip must not take this whole process down -
        # found for real during this pass's own docker-compose verification
        # (a deliberate, brief `docker compose stop redis` to prove /readyz
        # correctly degrades - see server/observability_server.py - instead
        # crashed this service outright with an unhandled
        # redis.exceptions.ConnectionError from queue.advance_time). One
        # bad tick is skipped and retried next interval, the same
        # "isolate, don't crash the whole loop" reasoning
        # server/game_loop.py's own run_forever already applies per-game.
        try:
            # Only the replica currently holding this lease actually ticks
            # the shared queue - see server/redis/matchmaker_leader.py's own
            # docstring, and server/redis/matchmaking.py's, on why more than
            # one caller doing this concurrently double-counts waited_ms and
            # can double-claim a match. Every replica (leader or not) still
            # reaches this point every tick_interval_s, so whichever one is
            # leader notices a crashed predecessor's expired lease and takes
            # over within MATCHMAKER_LEADER_TTL_MS, not a whole
            # tick_interval_s later.
            if leader.acquire_or_renew():
                await _run_one_tick(queue, nats_connection, elapsed_ms)
        except Exception:
            _logger.exception("matchmaker tick failed - skipping this tick")


async def _run_one_tick(queue: RedisMatchmakingQueue, nats_connection, elapsed_ms: int) -> None:
    tick = queue.advance_time(elapsed_ms)
    _QUEUE_DEPTH_GAUGE.set(queue.queue_depth())
    for username in tick.timed_out:
        username_ctx.set(username)
        await nats_connection.publish(MatchmakingTimeout.SUBJECT, MatchmakingTimeout(username=username).encode())
    for username, seconds_remaining in tick.due_for_status:
        username_ctx.set(username)
        event = MatchmakingStatus(username=username, seconds_remaining=seconds_remaining)
        await nats_connection.publish(MatchmakingStatus.SUBJECT, event.encode())

    match = queue.find_match()
    if match is not None:
        white_username, black_username = match
        username_ctx.set(white_username)
        queue.remove(white_username)
        queue.remove(black_username)
        event = MatchFound(white_username=white_username, black_username=black_username)
        await nats_connection.publish(MatchFound.SUBJECT, event.encode())
        _logger.info("matched '%s' vs '%s'", white_username, black_username)


async def _main() -> None:
    redis_url = os.environ["REDIS_URL"]
    nats_url = os.environ["NATS_URL"]
    tick_interval_s = float(os.environ.get("MATCHMAKER_TICK_INTERVAL_S", DEFAULT_TICK_INTERVAL_S))

    queue = RedisMatchmakingQueue(redis_url)
    leader = MatchmakerLeaderElection(redis_url)
    nats_connection = await nats.connect(nats_url)

    async def _on_message(msg) -> None:
        await _on_matchmaking_requested(queue, msg)

    await nats_connection.subscribe(MatchmakingRequested.SUBJECT, cb=_on_message)

    import redis as redis_lib

    # Explicit, short timeouts - redis-py's own default is *no* timeout at
    # all, which would hang this check instead of failing it fast.
    health_redis_client = redis_lib.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)

    health_port = int(os.environ.get("HEALTH_PORT", 9102))
    start_observability_server(
        health_port,
        {"redis": lambda: bool(health_redis_client.ping()), "nats": lambda: nats_connection.is_connected},
    )

    _logger.info("matchmaker running (redis=%s nats=%s)", redis_url, nats_url)
    await _run_forever(queue, nats_connection, tick_interval_s, leader)


def main() -> None:  # pragma: no cover
    configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
