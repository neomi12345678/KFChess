"""Account persistence for the Home-screen login: username + password +
rating, saved in a SQLite DB on the server side (per the Home-screen
slide). "Just for presentation" scope, same as the plain-username login it
replaces - a first LOGIN for a never-seen username registers it on the spot
with whatever password came with it; there's no separate registration step.
"""

import hashlib
import os
import sqlite3
import threading
from dataclasses import dataclass

STARTING_RATING = 1200

# PBKDF2-SHA256 with a random per-account salt - no extra dependency
# (bcrypt/passlib), but still never stores a password in plain text or
# lets two equal passwords hash identically.
_HASH_NAME = "sha256"
_ITERATIONS = 200_000


class InvalidCredentialsError(Exception):
    """Raised when a *returning* username's password doesn't match what
    was stored when it was first registered."""


@dataclass(frozen=True)
class Account:
    username: str
    rating: int


class AccountStore:
    """db_path has no default on purpose - every call site must say
    explicitly whether it means a real, persistent file (server/main.py) or
    an isolated ":memory:" database (tests), rather than silently sharing
    whatever the default happened to be."""

    def __init__(self, db_path: str):
        # check_same_thread=False - server/ws_server.py runs login() in a
        # thread-pool executor (see its own docstring for why: the ~200k-
        # iteration PBKDF2 hash below is deliberately slow, and running it
        # on the asyncio event loop thread would freeze every connection
        # and every in-progress game's tick for that long, not just this
        # one login). _lock is what keeps that safe - every call still
        # only ever touches this connection one at a time, just not always
        # from the same thread, which is all sqlite3 actually requires.
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        # Reentrant - login() calls _register() while already holding it.
        self._lock = threading.RLock()
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                username TEXT PRIMARY KEY,
                password_hash BLOB NOT NULL,
                password_salt BLOB NOT NULL,
                rating INTEGER NOT NULL
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    # Registers the username with this password and the starting rating the
    # first time it's ever seen; any later call re-checks the password
    # against what was stored then. Either way returns the account's
    # current (persisted) rating, never a stale in-memory guess.
    def login(self, username: str, password: str) -> Account:
        with self._lock:
            row = self._connection.execute(
                "SELECT password_hash, password_salt, rating FROM accounts WHERE username = ?",
                (username,),
            ).fetchone()

            if row is None:
                return self._register(username, password)

            stored_hash, salt, rating = row
            if _hash_password(password, salt) != stored_hash:
                raise InvalidCredentialsError(f"wrong password for '{username}'")

            return Account(username=username, rating=rating)

    def rating_for(self, username: str) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT rating FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            return row[0]

    def update_rating(self, username: str, rating: int) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE accounts SET rating = ? WHERE username = ?", (rating, username)
            )
            self._connection.commit()

    def _register(self, username: str, password: str) -> Account:
        with self._lock:
            salt = os.urandom(16)
            password_hash = _hash_password(password, salt)
            self._connection.execute(
                "INSERT INTO accounts (username, password_hash, password_salt, rating) VALUES (?, ?, ?, ?)",
                (username, password_hash, salt, STARTING_RATING),
            )
            self._connection.commit()
            return Account(username=username, rating=STARTING_RATING)


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(_HASH_NAME, password.encode("utf-8"), salt, _ITERATIONS)
