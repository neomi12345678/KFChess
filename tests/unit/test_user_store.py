import pytest

from server.accounts import InvalidCredentialsError, UserStore
from server.accounts_db import open_accounts_database


@pytest.fixture
def store():
    # ":memory:" - a real SQLite database, just an isolated, disposable one
    # per test (see server/accounts_db.py's own db_path docstring for why
    # there's no default to fall back on instead).
    return UserStore(open_accounts_database(":memory:"))


def test_first_login_for_a_username_registers_it(store):
    account = store.login("alice", "secret123")

    assert account.username == "alice"


def test_a_returning_username_with_the_correct_password_logs_in(store):
    store.login("alice", "secret123")

    account = store.login("alice", "secret123")

    assert account.username == "alice"


def test_a_returning_username_with_the_wrong_password_is_rejected(store):
    store.login("alice", "secret123")

    with pytest.raises(InvalidCredentialsError):
        store.login("alice", "wrong-password")


def test_two_different_usernames_dont_collide(store):
    store.login("alice", "secret123")
    store.login("bob", "different-password")

    # Each keeps its own password - bob's password must never unlock alice's
    # account, even though both share the same accounts table.
    with pytest.raises(InvalidCredentialsError):
        store.login("alice", "different-password")
