"""Redis-backed Game Server Shard registry - each shard (server/main.py's
game-server) registers itself here on a heartbeat, so the Game Allocator
(services/game_allocator/main.py) can discover which shards are actually alive
right now instead of being told a single, hardcoded address up front
(Server_Design.md §12's own open question on this). Same "lease, not a
static entry" reasoning as this same module's neighbor,
services/game_allocator/main.py's own _acquire_lease for room ownership (Server_Design.md
§4): a shard that crashes or is killed simply stops heartbeating, and its
own registration expires on its own - nothing else has to notice the crash
and clean up after it.

Plain sync `redis` client, same reasoning as server/redis/busy_set.py and
server/redis/matchmaking.py: every call site here (a periodic heartbeat
tick, and a per-allocation shard pick) is a cheap, local Redis round-trip
that doesn't need a dedicated async client to stay fast enough.

Note this module lives at server/redis/shard_registry.py, importing the
third-party `redis` package by its bare top-level name below - Python 3's
imports are absolute by default, so `import redis` here resolves to the
installed library on sys.path, not to this package (server.redis)
importing itself.
"""

import random
import time
from typing import List, Optional

import redis

_SHARD_KEY_PREFIX = "kfchess:shards:"


class ShardRegistry:
    def __init__(self, redis_url: str, ttl_ms: int = 10_000):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._ttl_ms = ttl_ms

    def register(self, shard_address: str) -> None:
        # PX, not a plain SET - see this module's own docstring on why a
        # lease (not a static entry) is the point.
        self._redis.set(f"{_SHARD_KEY_PREFIX}{shard_address}", str(time.time()), px=self._ttl_ms)

    def list_live_shards(self) -> List[str]:
        # scan_iter (cursor-based SCAN), not KEYS - doesn't block Redis,
        # even though at today's scale (a handful of shards at most) it
        # wouldn't actually matter either way.
        return [key[len(_SHARD_KEY_PREFIX):] for key in self._redis.scan_iter(match=f"{_SHARD_KEY_PREFIX}*")]

    def pick_shard(self) -> Optional[str]:
        live_shards = self.list_live_shards()
        return random.choice(live_shards) if live_shards else None
