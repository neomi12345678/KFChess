"""Login persistence for the Home-screen login: username + password,
verified against the shared accounts table (see server/accounts_db.py) -
the authentication half of what used to be one AccountStore doing both
this and ELO bookkeeping. server/rating_store.py's RatingStore is the
sibling half, for the rating number alone - genuinely separate concerns
(who you are vs. how good you are) that only happen to share one table.
"Just for presentation" scope, same as the plain-username login it
replaces - a first LOGIN for a never-seen username registers it on the
spot with whatever password came with it, at STARTING_RATING (read back
only through RatingStore, never returned from here); there's no separate
registration step.
"""

import hashlib
import os
from dataclasses import dataclass

from server.accounts_db import AccountsDatabase

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


class UserStore:
    def __init__(self, database: AccountsDatabase):
        self._database = database

    # Registers the username with this password and the starting rating
    # the first time it's ever seen; any later call re-checks the password
    # against what was stored then. Runs off the asyncio event loop
    # entirely, via the default thread-pool executor (see
    # server/ws_server.py's own _handle_login) - the PBKDF2 hash below is
    # deliberately slow, and running it directly on the event loop would
    # freeze every other connection's messages and every in-progress
    # game's tick for that long, not just this one login. The shared
    # AccountsDatabase's lock (not check_same_thread=False alone) is what
    # makes that safe alongside RatingStore's own calls on the event-loop
    # thread.
    def login(self, username: str, password: str) -> Account:
        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT password_hash, password_salt FROM accounts WHERE username = ?",
                (username,),
            ).fetchone()

            if row is None:
                return self._register(username, password)

            stored_hash, salt = row
            if _hash_password(password, salt) != stored_hash:
                raise InvalidCredentialsError(f"wrong password for '{username}'")

            return Account(username=username)

    def _register(self, username: str, password: str) -> Account:
        with self._database.lock:
            salt = os.urandom(16)
            password_hash = _hash_password(password, salt)
            self._database.connection.execute(
                "INSERT INTO accounts (username, password_hash, password_salt, rating) VALUES (?, ?, ?, ?)",
                (username, password_hash, salt, STARTING_RATING),
            )
            self._database.connection.commit()
            return Account(username=username)


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(_HASH_NAME, password.encode("utf-8"), salt, _ITERATIONS)
