"""Standalone Persistence Worker service - the "Persistence Worker" role
from Server_Design.md §3/§8/§11 (docs/server-scaling-design branch): a
stateless consumer of the game.finished control-plane event
(server/nats/lifecycle.py's NatsLifecyclePublisher), writing durable game
results to PostgreSQL. Runs as its own deployable, decoupled from any one
Game Server Shard's own process/tick loop - a slow or briefly-down
Postgres here never blocks gameplay, since GameLoop only ever
fire-and-forgets this event and moves on (see server/game_loop.py's own
_advance_game).

Deliberately scoped to *results* persistence only (participants + final
ratings), not a rewrite of the existing, already-working synchronous
rating write in server/game_loop.py's _advance_game - that write stays
exactly as it is; this adds a genuinely new capability (durable game
history) rather than replacing an existing one.

Subscribes to:
    game.finished  {"game_id": str, "room_id": str|null,
                     "white_username": str, "black_username": str,
                     "ratings": {"white": int, "black": int},
                     "published_at": float}

published_at (a unix timestamp - see server/nats/lifecycle.py's own
NatsLifecyclePublisher.game_finished) is what lets this service report
Server_Design.md §9's own "consumer lag per Persistence Worker" metric -
read defensively (payload.get, not payload[]) since it's a newer field
older publishers/tests may not send; the gauge simply isn't updated for
those, rather than this handler failing to record a real game over a
metric.
"""

import asyncio
import json
import logging
import os
import time

import nats
from prometheus_client import Gauge

from server.logging_config import configure_logging, room_id_ctx
from server.observability_server import start_observability_server
from server.postgres.game_history import PostgresGameHistoryStore

_logger = logging.getLogger(__name__)

_LAG_GAUGE = Gauge("kfchess_persistence_worker_lag_seconds", "Time between a game.finished publish and its processing")


def _record_from_payload(store: PostgresGameHistoryStore, payload: dict) -> None:
    ratings = payload["ratings"]
    store.record_game(
        payload["game_id"],
        payload["room_id"],
        payload["white_username"],
        payload["black_username"],
        ratings["white"],
        ratings["black"],
    )


async def _on_game_finished(store: PostgresGameHistoryStore, msg) -> None:
    payload = json.loads(msg.data)
    room_id_ctx.set(payload["room_id"] if payload["room_id"] is not None else payload["game_id"])
    _record_from_payload(store, payload)

    published_at = payload.get("published_at")
    if published_at is not None:
        _LAG_GAUGE.set(time.time() - published_at)

    _logger.info(
        "recorded game %s ('%s' vs '%s')", payload["game_id"], payload["white_username"], payload["black_username"]
    )


async def _main() -> None:
    database_url = os.environ["DATABASE_URL"]
    nats_url = os.environ["NATS_URL"]

    store = PostgresGameHistoryStore(database_url)
    nats_connection = await nats.connect(nats_url)

    async def _on_message(msg) -> None:
        await _on_game_finished(store, msg)

    await nats_connection.subscribe("game.finished", cb=_on_message)

    def _check_postgres() -> bool:
        import psycopg

        with psycopg.connect(database_url, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
        return True

    health_port = int(os.environ.get("HEALTH_PORT", 9104))
    start_observability_server(
        health_port, {"postgres": _check_postgres, "nats": lambda: nats_connection.is_connected}
    )

    _logger.info("persistence-worker running (database=%s nats=%s)", database_url, nats_url)
    await asyncio.Event().wait()  # driven entirely by the subscription callback above


def main() -> None:  # pragma: no cover
    configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
