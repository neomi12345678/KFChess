"""Redis-backed index of "where does this username's live game currently
sit" - the one piece of state a standalone API Gateway's own POST /login
(see services/api_gateway/main.py) needs that isn't otherwise visible
outside the process actually running the game: GameLoop's own in-memory
self._games dict is private to whichever process holds it, so a separate
REST process can't call active_game_for(username) directly the way
server/router.py's CommandRouter does in-process.

Deliberately narrow: this only ever answers "does username have a live
game right now, and as which seat" - never "is that seat currently
disconnected." That finer-grained fact stays entirely in-process (see
server/session.py's GameSession.mark_reconnected/is_disconnected, only
ever called from the same process that holds the live GameSession - see
server/router.py's CommandRouter.decide_identify, reached via a new
IDENTIFY websocket message, not this index). Mixing that into this index
would mean keeping it live-updated on every disconnect/reconnect
transition for no REST caller that actually needs it yet.

Written by server/game_loop.py's GameLoop._start_game (alongside
server/redis/busy_set.py's BusySet.add, for both seats), removed on game
end (game-over in GameLoop._advance_game, or GameLoop._fail_game -
alongside BusySet.remove in both).

Plain sync `redis` client, same reasoning as this package's other modules
(server/redis/matchmaking.py, server/redis/busy_set.py,
server/redis/shard_registry.py): every call here is a cheap, local Redis
round-trip from either GameLoop's own async tick loop or a REST request
handler, neither of which needs a dedicated async client to stay fast
enough.

Note this module lives at server/redis/active_game_index.py, importing the
third-party `redis` package by its bare top-level name below - Python 3's
imports are absolute by default, so `import redis` here resolves to the
installed library on sys.path, not to this package (server.redis)
importing itself.
"""

import json
from typing import Optional

import redis

from server.interfaces import ActiveGameLocation

_KEY_PREFIX = "kfchess:active_game:"


class ActiveGameIndex:
    def __init__(self, redis_url: str):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    def set(self, username: str, location: ActiveGameLocation) -> None:
        payload = {"game_id": location.game_id, "room_id": location.room_id, "seat": location.seat}
        self._redis.set(f"{_KEY_PREFIX}{username}", json.dumps(payload))

    def remove(self, username: str) -> None:
        self._redis.delete(f"{_KEY_PREFIX}{username}")

    def get(self, username: str) -> Optional[ActiveGameLocation]:
        raw = self._redis.get(f"{_KEY_PREFIX}{username}")
        if raw is None:
            return None
        payload = json.loads(raw)
        return ActiveGameLocation(game_id=payload["game_id"], room_id=payload["room_id"], seat=payload["seat"])
