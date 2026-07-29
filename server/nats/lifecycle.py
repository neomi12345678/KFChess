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

import json
from typing import Dict, Optional


class NatsLifecyclePublisher:
    def __init__(self, connection):
        self._connection = connection

    @classmethod
    async def connect(cls, nats_url: str) -> "NatsLifecyclePublisher":
        import nats

        connection = await nats.connect(nats_url)
        return cls(connection)

    async def game_created(
        self, game_id: str, room_id: Optional[str], white_username: str, black_username: str
    ) -> None:
        payload = {
            "game_id": game_id,
            "room_id": room_id,
            "white_username": white_username,
            "black_username": black_username,
        }
        await self._connection.publish("game.created", json.dumps(payload).encode("utf-8"))

    async def game_finished(
        self,
        game_id: str,
        room_id: Optional[str],
        white_username: str,
        black_username: str,
        ratings: Dict[str, int],
    ) -> None:
        payload = {
            "game_id": game_id,
            "room_id": room_id,
            "white_username": white_username,
            "black_username": black_username,
            "ratings": ratings,
        }
        await self._connection.publish("game.finished", json.dumps(payload).encode("utf-8"))
