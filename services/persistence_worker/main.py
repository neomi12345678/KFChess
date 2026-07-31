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

Subscribes to server/nats/events.py's GameFinished (subject "game.finished"):
    {"game_id": str, "room_id": str|null, "white_username": str,
     "black_username": str, "ratings": {"white": int, "black": int},
     "published_at": float}

Consumes in batches - Server_Design.md §8's own explicit requirement
("Persistence Workers consume it in batches, decoupled from whether the DB
is momentarily slow"): the NATS callback (_on_message) does no I/O at all,
just decodes and pushes onto an in-process asyncio.Queue; a separate
_run_batch_flusher task drains it into groups of up to PERSISTENCE_BATCH_SIZE
(server/server_config.py), flushed via one PostgresGameHistoryStore.
record_games_batch call (one executemany + one commit) rather than one
INSERT/commit round trip per game. A quiet period still flushes within
PERSISTENCE_BATCH_FLUSH_INTERVAL_MS of the oldest queued item, rather than
a small batch waiting indefinitely for more games to arrive and fill it.

published_at (a unix timestamp - see server/nats/lifecycle.py's own
NatsLifecyclePublisher.game_finished) is what lets this service report
Server_Design.md §9's own "consumer lag per Persistence Worker" metric -
GameFinished.published_at stays Optional and is read defensively
(event.published_at is not None, never assumed present) since it's a newer
field older publishers/tests may not send; the gauge reflects the *oldest*
unflushed item in a batch (the longest anything waited), the worst-case
lag a caller would actually experience, not just the latest one.
"""

import asyncio
import logging
import os
import time
from typing import List, Optional, Tuple

from prometheus_client import Gauge

from server.logging_config import configure_logging, room_id_ctx
from server.nats.client import connect as connect_nats
from server.nats.events import GameFinished
from server.observability_server import start_observability_server
from server.postgres.game_history import PostgresGameHistoryStore
from server.server_config import PERSISTENCE_BATCH_FLUSH_INTERVAL_MS, PERSISTENCE_BATCH_SIZE

_logger = logging.getLogger(__name__)

_LAG_GAUGE = Gauge("kfchess_persistence_worker_lag_seconds", "Time between a game.finished publish and its processing")
_BATCH_SIZE_GAUGE = Gauge("kfchess_persistence_worker_last_batch_size", "Number of games written in the most recent flush")


def _tuple_from_event(event: GameFinished) -> Tuple[str, Optional[str], str, str, int, int]:
    return (
        event.game_id,
        event.room_id,
        event.white_username,
        event.black_username,
        event.ratings["white"],
        event.ratings["black"],
    )


def _flush_batch(store: PostgresGameHistoryStore, batch: List[GameFinished]) -> None:
    store.record_games_batch([_tuple_from_event(event) for event in batch])
    _BATCH_SIZE_GAUGE.set(len(batch))

    published_ats = [event.published_at for event in batch if event.published_at is not None]
    if published_ats:
        _LAG_GAUGE.set(time.time() - min(published_ats))

    for event in batch:
        room_id_ctx.set(event.room_id if event.room_id is not None else event.game_id)
        _logger.info("recorded game %s ('%s' vs '%s')", event.game_id, event.white_username, event.black_username)


# Pulls one item (blocking - nothing to flush until something arrives),
# then keeps pulling more, non-blocking past a deadline, until either
# batch_size items have accumulated or flush_interval_s has elapsed since
# the first one - whichever comes first. A batch is flushed even if it
# never reaches batch_size, so a quiet period doesn't leave games waiting
# indefinitely.
async def _collect_batch(queue: "asyncio.Queue[GameFinished]", batch_size: int, flush_interval_s: float) -> List[GameFinished]:
    batch = [await queue.get()]
    deadline = asyncio.get_event_loop().time() + flush_interval_s
    while len(batch) < batch_size:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            batch.append(await asyncio.wait_for(queue.get(), timeout=remaining))
        except asyncio.TimeoutError:
            break
    return batch


async def _run_batch_flusher(
    queue: "asyncio.Queue[GameFinished]", store: PostgresGameHistoryStore, batch_size: int, flush_interval_s: float
) -> None:
    while True:
        batch = await _collect_batch(queue, batch_size, flush_interval_s)
        try:
            _flush_batch(store, batch)
        except Exception:
            # A batch a real Postgres outage can't absorb is lost rather
            # than retried forever and blocking every game *after* it too -
            # the same "never let a slow/broken DB stall this consumer"
            # principle this whole service exists for (see its own
            # docstring), just applied to a batch instead of one game.
            _logger.exception("failed to flush a batch of %d game(s) - they are lost", len(batch))


async def _main() -> None:
    database_url = os.environ["DATABASE_URL"]
    nats_url = os.environ["NATS_URL"]
    batch_size = int(os.environ.get("PERSISTENCE_BATCH_SIZE", PERSISTENCE_BATCH_SIZE))
    batch_flush_interval_s = float(os.environ.get("PERSISTENCE_BATCH_FLUSH_INTERVAL_MS", PERSISTENCE_BATCH_FLUSH_INTERVAL_MS)) / 1000

    store = PostgresGameHistoryStore(database_url)
    queue: "asyncio.Queue[GameFinished]" = asyncio.Queue()
    nats_connection = await connect_nats(nats_url)

    # Deliberately no I/O here - just decode and enqueue, so a slow flush
    # never backs up NATS message delivery for this subscription (see this
    # module's own docstring on why batching lives in a separate task).
    async def _on_message(msg) -> None:
        await queue.put(GameFinished.decode(msg.data))

    await nats_connection.subscribe(GameFinished.SUBJECT, cb=_on_message)
    asyncio.create_task(_run_batch_flusher(queue, store, batch_size, batch_flush_interval_s))

    def _check_postgres() -> bool:
        import psycopg

        with psycopg.connect(database_url, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
        return True

    health_port = int(os.environ.get("HEALTH_PORT", 9104))
    start_observability_server(
        health_port, {"postgres": _check_postgres, "nats": lambda: nats_connection.is_connected}
    )

    _logger.info(
        "persistence-worker running (database=%s nats=%s batch_size=%d flush_interval_s=%.1f)",
        database_url, nats_url, batch_size, batch_flush_interval_s,
    )
    await asyncio.Event().wait()  # driven entirely by _run_batch_flusher above


def main() -> None:  # pragma: no cover
    configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
