import pytest

from server.accounts import STARTING_RATING, AccountStore, InvalidCredentialsError


@pytest.fixture
def store():
    # ":memory:" - a real SQLite database, just an isolated, disposable one
    # per test (see AccountStore's own db_path docstring for why there's no
    # default to fall back on instead).
    store = AccountStore(":memory:")
    yield store
    store.close()


def test_first_login_for_a_username_registers_it_at_the_starting_rating(store):
    account = store.login("alice", "secret123")

    assert account.username == "alice"
    assert account.rating == STARTING_RATING


def test_a_returning_username_with_the_correct_password_logs_in(store):
    store.login("alice", "secret123")

    account = store.login("alice", "secret123")

    assert account.username == "alice"
    assert account.rating == STARTING_RATING


def test_a_returning_username_with_the_wrong_password_is_rejected(store):
    store.login("alice", "secret123")

    with pytest.raises(InvalidCredentialsError):
        store.login("alice", "wrong-password")


def test_rating_for_reads_the_currently_persisted_rating(store):
    store.login("alice", "secret123")

    assert store.rating_for("alice") == STARTING_RATING


def test_update_rating_persists_across_a_later_login(store):
    store.login("alice", "secret123")

    store.update_rating("alice", 1250)

    assert store.rating_for("alice") == 1250
    account = store.login("alice", "secret123")
    assert account.rating == 1250


def test_two_different_usernames_dont_collide(store):
    store.login("alice", "secret123")
    store.login("bob", "different-password")

    # Each keeps its own password - bob's password must never unlock alice's
    # account, even though both share the same AccountStore/table.
    with pytest.raises(InvalidCredentialsError):
        store.login("alice", "different-password")
