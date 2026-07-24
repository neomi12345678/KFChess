import pytest

from server.accounts import STARTING_RATING, UserStore
from server.accounts_db import open_accounts_database
from server.rating_store import RatingStore


@pytest.fixture
def database():
    return open_accounts_database(":memory:")


@pytest.fixture
def rating_store(database):
    # Rows only ever exist once UserStore.login has created them (see
    # RatingStore's own docstring) - every RatingStore test logs its
    # usernames in first, through the same shared database, before ever
    # reading/writing a rating.
    UserStore(database).login("alice", "secret123")
    return RatingStore(database)


def test_rating_for_reads_the_starting_rating_right_after_registration(rating_store):
    assert rating_store.rating_for("alice") == STARTING_RATING


def test_update_rating_persists_the_new_value(rating_store):
    rating_store.update_rating("alice", 1250)

    assert rating_store.rating_for("alice") == 1250
