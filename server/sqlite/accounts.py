"""SQLite-backed UserStore - "just for presentation" scope, same as the
plain-username login it replaces: a first LOGIN for a never-seen username
registers it on the spot with whatever password came with it, at
STARTING_RATING (read back only through RatingStore, never returned from
here); there's no separate registration step. See server/accounts.py for
the shared Account/InvalidCredentialsError/_hash_password this depends on
(kept there, not duplicated, since hashing is the one part of this that's
security-sensitive), and server/postgres/accounts.py's PostgresUserStore
for the Postgres-backed sibling server/main.py's _build_stores picks
between (gated behind DATABASE_URL).
"""

import os

from server.accounts import Account, InvalidCredentialsError, _hash_password
from server.server_config import STARTING_RATING
from server.sqlite.accounts_db import AccountsDatabase


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
