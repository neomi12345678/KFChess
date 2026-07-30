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

Each heartbeat also carries the shard's own current live-room count (see
server/main.py's own _run_shard_heartbeat, which reads it straight from
GameLoop.active_game_count) - what pick_shard's own max_rooms_per_shard
filter (Server_Design.md §9's own "bound the blast radius" - see
server/server_config.py's MAX_ROOMS_PER_SHARD) uses to skip a shard already
at capacity. Self-reported by each shard rather than counted externally
(e.g. by scanning server/redis/room_shard_index.py's RoomShardIndex) since
that index only ever covers room-based games, never a PLAY match (see its
own docstring) - a shard's own in-memory GameLoop._games is the one place
that already counts both correctly.

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

import json
import random
from typing import List, Optional

import redis

_SHARD_KEY_PREFIX = "kfchess:shards:"


class ShardRegistry:
    def __init__(self, redis_url: str, ttl_ms: int = 10_000):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._ttl_ms = ttl_ms

    def register(self, shard_address: str, room_count: int = 0) -> None:
        # PX, not a plain SET - see this module's own docstring on why a
        # lease (not a static entry) is the point.
        payload = json.dumps({"room_count": room_count})
        self._redis.set(f"{_SHARD_KEY_PREFIX}{shard_address}", payload, px=self._ttl_ms)

    def list_live_shards(self) -> List[str]:
        # scan_iter (cursor-based SCAN), not KEYS - doesn't block Redis,
        # even though at today's scale (a handful of shards at most) it
        # wouldn't actually matter either way.
        return [key[len(_SHARD_KEY_PREFIX):] for key in self._redis.scan_iter(match=f"{_SHARD_KEY_PREFIX}*")]

    # None means "not currently live" (no heartbeat on file at all) -
    # distinct from 0, a live shard that's simply empty right now.
    def room_count_for(self, shard_address: str) -> Optional[int]:
        raw = self._redis.get(f"{_SHARD_KEY_PREFIX}{shard_address}")
        if raw is None:
            return None
        return json.loads(raw)["room_count"]

    # max_rooms_per_shard=None (the default) keeps today's behavior exactly
    # - pick uniformly among every live shard. Set (see
    # services/game_allocator/main.py's own use, server/server_config.py's
    # MAX_ROOMS_PER_SHARD), this filters out any shard already at or over
    # that room count first - a shard with no room-count data yet (should
    # only happen for the first heartbeat after this field was introduced,
    # mid-rolling-deploy) is treated as 0, not excluded, since "unknown"
    # isn't "full."
    def pick_shard(self, max_rooms_per_shard: Optional[int] = None) -> Optional[str]:
        live_shards = self.list_live_shards()
        if max_rooms_per_shard is not None:
            live_shards = [
                shard for shard in live_shards if (self.room_count_for(shard) or 0) < max_rooms_per_shard
            ]
        return random.choice(live_shards) if live_shards else None
