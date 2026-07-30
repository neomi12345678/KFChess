"""Redis-backed sibling of server/matchmaking.py's MatchmakingQueue, for
the Dockerized deployment (see docker-compose.yml, gated behind the
REDIS_URL env var in server/main.py) - same five-method surface
(server/interfaces.py's MatchmakingQueueProtocol), but a genuinely
different pairing algorithm from its in-memory sibling: Server_Design.md
§5's own "Matchmaking queue | Redis Sorted Set (`ZADD` by rating) | O(log n)
proximity lookup, globally shared." find_match here returns the pair with
the *smallest rating gap* anywhere in the queue (still bounded by
RATING_RANGE), not "the first pair found in insertion order" the in-memory
MatchmakingQueue uses (see its own docstring) - a deliberate divergence,
not an oversight: the in-memory queue is a single process's local fallback
(no separate Matchmaker service involved), while this class is what the
real standalone Matchmaker service (services/matchmaker/main.py) runs in
the actual distributed deployment, so it's the one Server_Design.md §5
is actually describing.

kfchess:matchmaking:by_rating is a ZSET (member=username, score=rating) -
the index find_match scans; kfchess:matchmaking:waiting is a Hash holding
each waiting username's {rating, waited_ms, last_notified_ms} - the
bookkeeping advance_time ages. Both are written together on every
enqueue/remove so they never disagree about who's currently waiting.

Uses a plain sync `redis` client, not `redis.asyncio`: enqueue/remove/
is_waiting are called from server/router.py's CommandRouter, which is
deliberately never async (see its own docstring - none of its methods
touch a websocket, JSON, or an event loop). Making these async would
cascade into an async rewrite of CommandRouter and every
server/ws_server.py call site for no real benefit at this deployment's
scale. advance_time/find_match are called from GameLoop's own async tick
loop, but a local Redis round trip is sub-millisecond - the same "brief,
synchronous, lock-guarded I/O directly on the event loop" trade-off
server/sqlite/rating_store.py's RatingStore (and server/postgres/accounts.py's
PostgresRatingStore) already make, for the same reason: it's fast enough
in practice not to matter, and keeping this class's whole surface
synchronous is what lets it be a drop-in for MatchmakingQueue everywhere,
not just in GameLoop.

Note this module lives at server/redis/matchmaking.py, importing the
third-party `redis` package by its bare top-level name below - Python 3's
imports are absolute by default, so `import redis` here resolves to the
installed library on sys.path, not to this package (server.redis)
importing itself.
"""

import json
import math
from typing import List, Optional, Tuple

import redis

from server.interfaces import MatchmakingTick
from server.server_config import MATCHMAKING_STATUS_INTERVAL_MS, MATCHMAKING_TIMEOUT_MS, RATING_RANGE

_RATING_INDEX_KEY = "kfchess:matchmaking:by_rating"
_WAITING_KEY = "kfchess:matchmaking:waiting"


class RedisMatchmakingQueue:
    def __init__(
        self,
        redis_url: str,
        timeout_ms: int = MATCHMAKING_TIMEOUT_MS,
        status_interval_ms: int = MATCHMAKING_STATUS_INTERVAL_MS,
    ):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._timeout_ms = timeout_ms
        self._status_interval_ms = status_interval_ms

    # ZADD on an existing member just updates its score in place - exactly
    # what a re-enqueue (a rating that may have changed since the last
    # queue attempt) should do. The Hash write below always resets
    # waited_ms/last_notified_ms back to 0 regardless of whether the
    # username was already waiting, the same "wholesale overwrite, no
    # special-case code" behavior the in-memory MatchmakingQueue.enqueue
    # documents for itself.
    def enqueue(self, username: str, rating: int) -> None:
        self._redis.zadd(_RATING_INDEX_KEY, {username: rating})
        payload = json.dumps({"rating": rating, "waited_ms": 0, "last_notified_ms": 0})
        self._redis.hset(_WAITING_KEY, username, payload)

    def remove(self, username: str) -> None:
        self._redis.zrem(_RATING_INDEX_KEY, username)
        self._redis.hdel(_WAITING_KEY, username)

    def is_waiting(self, username: str) -> bool:
        return bool(self._redis.hexists(_WAITING_KEY, username))

    # Server_Design.md §9's own "queue depth per Matchmaker replica" metric
    # (see services/matchmaker/main.py's own kfchess_matchmaker_queue_depth
    # gauge) - HLEN is O(1), no need to pull every waiting entry just to
    # count them.
    def queue_depth(self) -> int:
        return self._redis.hlen(_WAITING_KEY)

    # Same two-list contract as server/matchmaking.py's own advance_time -
    # see MatchmakingTick's own docstring. One HGETALL round trip for every
    # waiting entry's state, rather than the old list-then-per-key lookups
    # this class used before the rating index became a ZSET instead of an
    # insertion-order List.
    def advance_time(self, elapsed_ms: int) -> MatchmakingTick:
        timed_out: List[str] = []
        due_for_status: List[Tuple[str, int]] = []

        for username, raw in self._redis.hgetall(_WAITING_KEY).items():
            entry = json.loads(raw)
            entry["waited_ms"] += elapsed_ms
            if entry["waited_ms"] >= self._timeout_ms:
                timed_out.append(username)
                continue

            last_notified_ms = entry.get("last_notified_ms", 0)
            if entry["waited_ms"] - last_notified_ms >= self._status_interval_ms:
                entry["last_notified_ms"] = entry["waited_ms"]
                due_for_status.append((username, math.ceil((self._timeout_ms - entry["waited_ms"]) / 1000)))

            self._redis.hset(_WAITING_KEY, username, json.dumps(entry))

        for username in timed_out:
            self.remove(username)

        return MatchmakingTick(timed_out=timed_out, due_for_status=due_for_status)

    # The pair with the smallest rating gap anywhere in the queue, bounded
    # by RATING_RANGE - true O(log n)-built proximity search, not a scan in
    # insertion order (see this module's own docstring on why that's a
    # deliberate divergence from the in-memory queue). ZRANGE already
    # returns members sorted by score, so the minimum gap between *any* two
    # entries is always between some pair of *adjacent* entries in that
    # sorted order - checking each adjacent pair once (O(n)) is therefore
    # exhaustive, not a heuristic; no need to compare every pair (O(n^2)).
    def find_match(self) -> Optional[Tuple[str, str]]:
        entries = self._redis.zrange(_RATING_INDEX_KEY, 0, -1, withscores=True)

        best: Optional[Tuple[str, str]] = None
        best_gap: Optional[float] = None
        for (username_a, rating_a), (username_b, rating_b) in zip(entries, entries[1:]):
            gap = rating_b - rating_a
            if gap <= RATING_RANGE and (best_gap is None or gap < best_gap):
                best = (username_a, username_b)
                best_gap = gap

        return best
