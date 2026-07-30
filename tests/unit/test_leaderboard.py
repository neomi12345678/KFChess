"""Real Redis, no mocks - server/redis/leaderboard.py's Leaderboard and
LeaderboardRatingStore, the Server_Design.md §5 "Leaderboard | Redis Sorted
Set | Not a live `ORDER BY` over 100M rows - incremental updates instead."

Skipped unless KFCHESS_TEST_REDIS_URL is set:

    docker compose up -d redis
    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 python -m pytest tests/unit/test_leaderboard.py
"""

import os

import pytest

REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(REDIS_URL is None, reason="set KFCHESS_TEST_REDIS_URL to run these")


@pytest.fixture
def leaderboard():
    from server.redis.leaderboard import _LEADERBOARD_KEY, Leaderboard

    import redis as redis_lib

    redis_lib.Redis.from_url(REDIS_URL).delete(_LEADERBOARD_KEY)
    return Leaderboard(REDIS_URL)


def test_top_on_an_empty_leaderboard_is_empty(leaderboard):
    assert leaderboard.top() == []


def test_top_orders_highest_rating_first(leaderboard):
    leaderboard.set_rating("alice", 1200)
    leaderboard.set_rating("bob", 1500)
    leaderboard.set_rating("carol", 1350)

    assert leaderboard.top() == [("bob", 1500), ("carol", 1350), ("alice", 1200)]


def test_top_respects_the_limit(leaderboard):
    leaderboard.set_rating("alice", 1200)
    leaderboard.set_rating("bob", 1500)
    leaderboard.set_rating("carol", 1350)

    assert leaderboard.top(limit=2) == [("bob", 1500), ("carol", 1350)]


def test_set_rating_on_an_existing_username_updates_it_in_place(leaderboard):
    leaderboard.set_rating("alice", 1200)

    leaderboard.set_rating("alice", 1400)

    assert leaderboard.top() == [("alice", 1400)]


def test_rank_of_is_zero_indexed_from_the_top(leaderboard):
    leaderboard.set_rating("alice", 1200)
    leaderboard.set_rating("bob", 1500)

    assert leaderboard.rank_of("bob") == 0
    assert leaderboard.rank_of("alice") == 1


def test_rank_of_an_unranked_username_is_none(leaderboard):
    assert leaderboard.rank_of("nobody") is None


# LeaderboardRatingStore - wraps any RatingRepository so update_rating also
# keeps this ZSET in sync (see server/main.py's own use, wrapping whichever
# rating_store a shard already has).
def test_leaderboard_rating_store_updates_the_leaderboard_on_write(leaderboard):
    from server.redis.leaderboard import LeaderboardRatingStore

    class _FakeRatingStore:
        def __init__(self):
            self.ratings = {"alice": 1200}

        def rating_for(self, username):
            return self.ratings[username]

        def update_rating(self, username, rating):
            self.ratings[username] = rating

    inner = _FakeRatingStore()
    store = LeaderboardRatingStore(inner, leaderboard)

    store.update_rating("alice", 1350)

    assert inner.ratings["alice"] == 1350  # the wrapped store still gets the write
    assert leaderboard.top() == [("alice", 1350)]  # and the leaderboard reflects it


def test_leaderboard_rating_store_rating_for_passes_through(leaderboard):
    from server.redis.leaderboard import LeaderboardRatingStore

    class _FakeRatingStore:
        def rating_for(self, username):
            return 1234

        def update_rating(self, username, rating):
            raise AssertionError("not expected to be called")

    store = LeaderboardRatingStore(_FakeRatingStore(), leaderboard)

    assert store.rating_for("alice") == 1234
