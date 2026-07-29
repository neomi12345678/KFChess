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
                     "ratings": {"white": int, "black": int}}
"""

import asyncio
import json
import logging
import os

import nats

from server.postgres.game_history import PostgresGameHistoryStore

_logger = logging.getLogger(__name__)


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
    _record_from_payload(store, payload)
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

    _logger.info("persistence-worker running (database=%s nats=%s)", database_url, nats_url)
    await asyncio.Event().wait()  # driven entirely by the subscription callback above


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
