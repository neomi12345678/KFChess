"""Redis-backed cross-process "who's currently busy" set
(kfchess:busy_usernames) - the one piece of state a standalone api-gateway
needs that isn't otherwise visible outside the game-server process:
GameLoop's own in-memory active-games dict and RoomRegistry's own
in-memory room membership are both private Python objects inside whichever
process actually runs games/rooms (the merged WS-Gateway+Shard,
server/main.py's game-server) - a separate process's PLAY busy-check can't
reach into either directly, so it reads this set instead.

Deliberately covers only participants (room creator/opponent, seated
players) - not spectators, which today's in-process participant_state()
also treats as "busy" but this cross-process set does not. Flagged, not
silently dropped: with this simplification, a spectator could also queue
for PLAY via a REST endpoint that only checks this set.

Plain sync `redis` client, same reasoning as server/redis/matchmaking.py's
own RedisMatchmakingQueue: every call site here (RoomRegistry.create/join,
GameLoop._start_game/_advance_game/_fail_game) is either already
synchronous or a cheap, local Redis round-trip inside an async method that
doesn't need a dedicated async client to stay fast enough.

Note this module lives at server/redis/busy_set.py, importing the
third-party `redis` package by its bare top-level name below - Python 3's
imports are absolute by default, so `import redis` here resolves to the
installed library on sys.path, not to this package (server.redis)
importing itself.
"""

import redis

_BUSY_KEY = "kfchess:busy_usernames"


class BusySet:
    def __init__(self, redis_url: str):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    def add(self, username: str) -> None:
        self._redis.sadd(_BUSY_KEY, username)

    def remove(self, username: str) -> None:
        self._redis.srem(_BUSY_KEY, username)

    def contains(self, username: str) -> bool:
        return bool(self._redis.sismember(_BUSY_KEY, username))
