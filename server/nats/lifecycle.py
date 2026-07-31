"""NATS-backed publisher for the two coarse game-lifecycle events
server/game_loop.py's GameLoop can observe - low-volume control-plane
events (game-created, game-finished), never the high-frequency per-tick
gameplay stream itself (see Server_Design.md's own reasoning, on the
docs/server-scaling-design branch, for why that stays off the shared bus).

Gated behind the NATS_URL env var in server/main.py; GameLoop treats a
missing lifecycle_publisher (None) as a pure no-op, so nothing here is
required for a bare-metal run.

Note this module lives at server/nats/lifecycle.py, importing the
third-party `nats` package (nats-py) by its bare top-level name below -
Python 3's imports are absolute by default, so `import nats` here
resolves to the installed library on sys.path, not to this package
(server.nats) importing itself.
"""

import time
from typing import Dict, Optional

from server.nats.client import connect as connect_nats
from server.nats.events import GameCreated, GameFinished


class NatsLifecyclePublisher:
    def __init__(self, connection):
        self._connection = connection

    @classmethod
    async def connect(cls, nats_url: str) -> "NatsLifecyclePublisher":
        connection = await connect_nats(nats_url)
        return cls(connection)

    # Exposed read-only so server/main.py's own readiness check can read
    # this connection's is_connected property (a plain, thread-safe
    # boolean - see server/observability_server.py's own docstring on why
    # a synchronous read, not an awaited call, is what a background-thread
    # readiness check needs) without this class needing to know anything
    # about health checks itself.
    @property
    def connection(self):
        return self._connection

    async def game_created(
        self, game_id: str, room_id: Optional[str], white_username: str, black_username: str
    ) -> None:
        event = GameCreated(game_id=game_id, room_id=room_id, white_username=white_username, black_username=black_username)
        await self._connection.publish(GameCreated.SUBJECT, event.encode())

    async def game_finished(
        self,
        game_id: str,
        room_id: Optional[str],
        white_username: str,
        black_username: str,
        ratings: Dict[str, int],
    ) -> None:
        event = GameFinished(
            game_id=game_id,
            room_id=room_id,
            white_username=white_username,
            black_username=black_username,
            ratings=ratings,
            # Server_Design.md §9's own "consumer lag per Persistence
            # Worker" metric needs a publish-time timestamp to measure
            # against - nothing in this payload carried one before (see
            # services/persistence_worker/main.py's own lag gauge).
            published_at=time.time(),
        )
        await self._connection.publish(GameFinished.SUBJECT, event.encode())
