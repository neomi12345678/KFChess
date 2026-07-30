"""Redis-backed leaderboard - the literal Server_Design.md §5 requirement
("Leaderboard | Redis Sorted Set | Not a live `ORDER BY` over 100M rows -
incremental updates instead"). A single ZSET (kfchess:leaderboard) scored
by rating, updated incrementally on every rating change rather than ever
re-scanning the accounts table.

Written by LeaderboardRatingStore (server/main.py's own composition of this
class around whichever RatingRepository a deployment already uses - SQLite,
or Postgres for the Dockerized one) - the only place any account's rating
ever changes is server/session.py's GameSession.finalize_ratings_if_game_over,
so wrapping that one RatingRepository call site is sufficient to keep this
ZSET's scores in sync with the durable rating store, without threading a
Leaderboard dependency through GameSession/GameLoop themselves.

Read by services/api_gateway/main.py's own GET /leaderboard route - the one
place this fact is actually surfaced today (see that route's own docstring).

Plain sync `redis` client, same reasoning as this package's other modules
(server/redis/busy_set.py, server/redis/active_game_index.py): every call
here is a cheap, local Redis round-trip.

Note this module lives at server/redis/leaderboard.py, importing the
third-party `redis` package by its bare top-level name below - Python 3's
imports are absolute by default, so `import redis` here resolves to the
installed library on sys.path, not to this package (server.redis)
importing itself.
"""

from typing import List, Optional, Tuple

import redis

from server.interfaces import RatingRepository

_LEADERBOARD_KEY = "kfchess:leaderboard"


class Leaderboard:
    def __init__(self, redis_url: str):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    def set_rating(self, username: str, rating: int) -> None:
        self._redis.zadd(_LEADERBOARD_KEY, {username: rating})

    # Highest rating first (ZREVRANGE, not ZRANGE) - "leaderboard," not "the
    # lowest-rated players." Ties (equal ratings) come back in Redis's own
    # reverse-lexicographic order for tied scores - not meaningful here, no
    # caller depends on a specific tie order.
    def top(self, limit: int = 10) -> List[Tuple[str, int]]:
        entries = self._redis.zrevrange(_LEADERBOARD_KEY, 0, limit - 1, withscores=True)
        return [(username, int(rating)) for username, rating in entries]

    # 0-indexed, highest rating = rank 0 - None if username has never had a
    # rating recorded here (e.g. never finished a game yet).
    def rank_of(self, username: str) -> Optional[int]:
        rank = self._redis.zrevrank(_LEADERBOARD_KEY, username)
        return int(rank) if rank is not None else None


# Wraps any RatingRepository (server/sqlite/rating_store.py's RatingStore,
# server/postgres/accounts.py's PostgresRatingStore) so every update_rating
# call also keeps this Leaderboard's ZSET in sync - see this module's own
# docstring for why GameSession itself never needs to know a Leaderboard
# exists. Structurally satisfies RatingRepository itself (rating_for is a
# pure passthrough), so it's a drop-in replacement for the store it wraps.
class LeaderboardRatingStore:
    def __init__(self, inner: RatingRepository, leaderboard: Leaderboard):
        self._inner = inner
        self._leaderboard = leaderboard

    def rating_for(self, username: str) -> int:
        return self._inner.rating_for(username)

    def update_rating(self, username: str, rating: int) -> None:
        self._inner.update_rating(username, rating)
        self._leaderboard.set_rating(username, rating)
