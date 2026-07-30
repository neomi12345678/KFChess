"""Redis-backed `room_id -> shard_address` mapping - the literal
`Server_Design.md` §4 requirement ("A `room_id -> worker` mapping (Redis) -
maintained by the Game Allocator"), kept as its own tiny class rather than
folded into server/redis/rooms.py's RedisRoomRegistry: that module's own
docstring already draws the line between room *membership* (who's in the
room) and *which shard hosts the room's live GameSession*, calling the
latter "a separate concern" - this is that separate concern.

Written by services/game_allocator/main.py's own _allocate, the instant it
acquires a room's ownership lease (the moment it decides shard_address for
that room_id) - never by a Game Server Shard itself, matching §4's own
"maintained by the Game Allocator" wording. Read by
services/api_gateway/main.py (to answer a spectator's REST join with
nothing - see its own docstring for why no lookup is even needed there) and
by services/ws_gateway/main.py (to resolve which shard to relay a
spectator's connection to, per §6.2's "any WS Gateway asks Game Allocator
for the current owner... Spectators do the same").

Deliberately not the same key as services/game_allocator/main.py's own
_acquire_lease (`kfchess:game:{game_id}:owner`) - that key carries a short,
intentional TTL (a one-shot guard against double-allocation during the
handoff itself, not meant to outlive it), while this mapping must stay
valid for as long as the room's game is actually live.

Plain sync `redis` client, same reasoning as this package's other modules
(server/redis/busy_set.py, server/redis/active_game_index.py,
server/redis/shard_registry.py): every call here is a cheap, local Redis
round-trip, not something worth a dedicated async client.

Note this module lives at server/redis/room_shard_index.py, importing the
third-party `redis` package by its bare top-level name below - Python 3's
imports are absolute by default, so `import redis` here resolves to the
installed library on sys.path, not to this package (server.redis)
importing itself.
"""

from typing import Optional

import redis

_KEY_PREFIX = "kfchess:room_shard:"


class RoomShardIndex:
    def __init__(self, redis_url: str):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    def set(self, room_id: str, shard_address: str) -> None:
        self._redis.set(f"{_KEY_PREFIX}{room_id}", shard_address)

    def remove(self, room_id: str) -> None:
        self._redis.delete(f"{_KEY_PREFIX}{room_id}")

    def get(self, room_id: str) -> Optional[str]:
        return self._redis.get(f"{_KEY_PREFIX}{room_id}")
