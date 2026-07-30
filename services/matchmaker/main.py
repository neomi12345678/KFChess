"""Standalone Matchmaker service - the tick loop server/game_loop.py's
GameLoop used to run in-process (_advance_matchmaking/_try_start_a_match,
now skipped once EXTERNAL_MATCHMAKER=1 is set on the game-server - see
GameLoop.start_matchmaking_relay's own docstring for why the two can't run
at once), pulled out into its own deployable so matchmaking pairing keeps
running independently of any one game-server instance.

Reuses server/redis/matchmaking.py's RedisMatchmakingQueue unchanged - the
same two Redis keys (kfchess:matchmaking:order/kfchess:matchmaking:waiting)
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
import json
import logging
import os

import nats

from server.logging_config import configure_logging, username_ctx
from server.redis.matchmaking import RedisMatchmakingQueue
from server.server_config import DEFAULT_TICK_INTERVAL_S

_logger = logging.getLogger(__name__)


async def _on_matchmaking_requested(queue: RedisMatchmakingQueue, msg) -> None:
    payload = json.loads(msg.data)
    username_ctx.set(payload["username"])
    queue.enqueue(payload["username"], payload["rating"])


async def _run_forever(queue: RedisMatchmakingQueue, nats_connection, tick_interval_s: float) -> None:
    last = asyncio.get_event_loop().time()
    while True:
        await asyncio.sleep(tick_interval_s)
        now = asyncio.get_event_loop().time()
        elapsed_ms = int((now - last) * 1000)
        last = now

        tick = queue.advance_time(elapsed_ms)
        for username in tick.timed_out:
            username_ctx.set(username)
            await nats_connection.publish(
                "matchmaking.timeout", json.dumps({"username": username}).encode("utf-8")
            )
        for username, seconds_remaining in tick.due_for_status:
            username_ctx.set(username)
            payload = {"username": username, "seconds_remaining": seconds_remaining}
            await nats_connection.publish("matchmaking.status", json.dumps(payload).encode("utf-8"))

        match = queue.find_match()
        if match is not None:
            white_username, black_username = match
            username_ctx.set(white_username)
            queue.remove(white_username)
            queue.remove(black_username)
            payload = {"white_username": white_username, "black_username": black_username}
            await nats_connection.publish("match.found", json.dumps(payload).encode("utf-8"))
            _logger.info("matched '%s' vs '%s'", white_username, black_username)


async def _main() -> None:
    redis_url = os.environ["REDIS_URL"]
    nats_url = os.environ["NATS_URL"]
    tick_interval_s = float(os.environ.get("MATCHMAKER_TICK_INTERVAL_S", DEFAULT_TICK_INTERVAL_S))

    queue = RedisMatchmakingQueue(redis_url)
    nats_connection = await nats.connect(nats_url)

    async def _on_message(msg) -> None:
        await _on_matchmaking_requested(queue, msg)

    await nats_connection.subscribe("matchmaking.requested", cb=_on_message)

    _logger.info("matchmaker running (redis=%s nats=%s)", redis_url, nats_url)
    await _run_forever(queue, nats_connection, tick_interval_s)


def main() -> None:  # pragma: no cover
    configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
