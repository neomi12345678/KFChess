"""Redis-backed sibling of server/matchmaking.py's MatchmakingQueue, for
the Dockerized deployment (see docker-compose.yml, gated behind the
REDIS_URL env var in server/main.py) - same five-method surface
(server/interfaces.py's MatchmakingQueueProtocol), same insertion-order-
scanned pairing algorithm, just persisted in Redis instead of a local
dict, so the queue survives a game-server container restart instead of
being silently dropped.

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

Critical constraint (see Server_Design.md's own callout on this): the
in-memory MatchmakingQueue.find_match depends on Python dict insertion
order - "first pair anywhere in queue order within RATING_RANGE", not
"nearest rating" - so this can't be a Redis Sorted Set scored by rating
without silently changing which pair gets matched first. Instead: a
Redis List (_ORDER_KEY) preserves enqueue order exactly the way dict
insertion order already does, and a Redis Hash (_WAITING_KEY) holds each
waiting username's {rating, waited_ms} - together they reproduce the
exact same O(n^2) nested-scan algorithm, just reading from Redis instead
of a local dict.

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

_ORDER_KEY = "kfchess:matchmaking:order"
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

    # HSET's return value distinguishes "this field didn't exist before"
    # (1) from "this field already existed and was just overwritten" (0) -
    # only the former should also push onto the order list, the same way
    # a plain dict's `self._waiting[username] = ...` on an *existing* key
    # overwrites the value in place without moving it in iteration order.
    # The whole-blob overwrite is also what resets last_notified_ms to 0 on
    # a re-enqueue, same as waited_ms - no special-case code needed.
    def enqueue(self, username: str, rating: int) -> None:
        payload = json.dumps({"rating": rating, "waited_ms": 0, "last_notified_ms": 0})
        is_new = self._redis.hset(_WAITING_KEY, username, payload) == 1
        if is_new:
            self._redis.rpush(_ORDER_KEY, username)

    def remove(self, username: str) -> None:
        self._redis.hdel(_WAITING_KEY, username)
        self._redis.lrem(_ORDER_KEY, 0, username)

    def is_waiting(self, username: str) -> bool:
        return bool(self._redis.hexists(_WAITING_KEY, username))

    # Server_Design.md §9's own "queue depth per Matchmaker replica" metric
    # (see services/matchmaker/main.py's own kfchess_matchmaker_queue_depth
    # gauge) - HLEN is O(1), no need to pull every waiting entry just to
    # count them.
    def queue_depth(self) -> int:
        return self._redis.hlen(_WAITING_KEY)

    # Same two-list contract as server/matchmaking.py's own advance_time -
    # see MatchmakingTick's own docstring (server/interfaces.py) - kept to
    # exactly one hset per surviving entry, same as before this method
    # tracked a notify boundary at all.
    def advance_time(self, elapsed_ms: int) -> MatchmakingTick:
        timed_out: List[str] = []
        due_for_status: List[Tuple[str, int]] = []

        for username in self._redis.lrange(_ORDER_KEY, 0, -1):
            raw = self._redis.hget(_WAITING_KEY, username)
            if raw is None:
                continue  # order list and hash briefly disagree mid-call; ignore, not fatal

            entry = json.loads(raw)
            entry["waited_ms"] += elapsed_ms
            if entry["waited_ms"] >= self._timeout_ms:
                timed_out.append(username)
                continue

            # .get(..., 0) tolerates a pre-upgrade entry with no such field
            # yet (a rolling deploy's in-flight queue), rather than a
            # KeyError mid-migration.
            last_notified_ms = entry.get("last_notified_ms", 0)
            if entry["waited_ms"] - last_notified_ms >= self._status_interval_ms:
                entry["last_notified_ms"] = entry["waited_ms"]
                due_for_status.append((username, math.ceil((self._timeout_ms - entry["waited_ms"]) / 1000)))

            self._redis.hset(_WAITING_KEY, username, json.dumps(entry))

        for username in timed_out:
            self.remove(username)

        return MatchmakingTick(timed_out=timed_out, due_for_status=due_for_status)

    def find_match(self) -> Optional[Tuple[str, str]]:
        usernames = self._redis.lrange(_ORDER_KEY, 0, -1)
        if not usernames:
            return None

        entries = [
            (username, json.loads(raw)["rating"])
            for username, raw in zip(usernames, self._redis.hmget(_WAITING_KEY, usernames))
            if raw is not None
        ]

        for i, (username_a, rating_a) in enumerate(entries):
            for username_b, rating_b in entries[i + 1 :]:
                if abs(rating_a - rating_b) <= RATING_RANGE:
                    return (username_a, username_b)

        return None
