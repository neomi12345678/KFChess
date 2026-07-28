"""PostgreSQL-backed sibling of server/sqlite/accounts_db.py +
server/sqlite/accounts.py + server/sqlite/rating_store.py, for the
Dockerized deployment (see docker-compose.yml, gated behind the
DATABASE_URL env var in server/main.py). SQLite's "?" placeholders and
Postgres's "%s" placeholders aren't interchangeable, so this can't just
point AccountsDatabase's existing connection at Postgres - it's a
parallel implementation of the same shapes instead (PostgresAccountsDatabase
mirrors AccountsDatabase, PostgresUserStore satisfies
server/interfaces.py's UserRepository the same way UserStore does,
PostgresRatingStore already matches RatingRepository structurally).
server/sqlite/'s own SQLite-backed classes are untouched - every existing
test that constructs them against ":memory:" keeps working exactly as
before.

Password hashing itself is deliberately NOT duplicated here - _hash_password
and the PASSWORD_HASH_NAME/PASSWORD_HASH_ITERATIONS constants it uses are
imported straight from server/accounts.py/server/server_config.py (the
shared login-domain module both UserStore implementations depend on), so
the one piece of this that's actually security-sensitive stays
single-sourced regardless of which store a deployment picks.
"""

import os
import threading
from dataclasses import dataclass, field

import psycopg

from server.accounts import Account, InvalidCredentialsError, _hash_password
from server.server_config import STARTING_RATING


@dataclass
class PostgresAccountsDatabase:
    connection: "psycopg.Connection"
    lock: threading.RLock = field(default_factory=threading.RLock)


def open_postgres_accounts_database(dsn: str) -> PostgresAccountsDatabase:
    connection = psycopg.connect(dsn, autocommit=False)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            username TEXT PRIMARY KEY,
            password_hash BYTEA NOT NULL,
            password_salt BYTEA NOT NULL,
            rating INTEGER NOT NULL
        )
        """
    )
    connection.commit()
    return PostgresAccountsDatabase(connection=connection)


class PostgresUserStore:
    """Same login/registration behavior as server/sqlite/accounts.py's
    UserStore - see its own docstring - just %s placeholders and a psycopg
    connection."""

    def __init__(self, database: PostgresAccountsDatabase):
        self._database = database

    def login(self, username: str, password: str) -> Account:
        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT password_hash, password_salt FROM accounts WHERE username = %s",
                (username,),
            ).fetchone()

            if row is None:
                return self._register(username, password)

            stored_hash, salt = row
            if _hash_password(password, bytes(salt)) != bytes(stored_hash):
                raise InvalidCredentialsError(f"wrong password for '{username}'")

            return Account(username=username)

    def _register(self, username: str, password: str) -> Account:
        with self._database.lock:
            salt = os.urandom(16)
            password_hash = _hash_password(password, salt)
            self._database.connection.execute(
                "INSERT INTO accounts (username, password_hash, password_salt, rating) VALUES (%s, %s, %s, %s)",
                (username, password_hash, salt, STARTING_RATING),
            )
            self._database.connection.commit()
            return Account(username=username)


class PostgresRatingStore:
    """Already matches server/interfaces.py's RatingRepository structurally,
    the same way server/sqlite/rating_store.py's RatingStore does - see its own
    docstring for why every row this reads/writes is assumed to already
    exist (created by PostgresUserStore.login's own INSERT)."""

    def __init__(self, database: PostgresAccountsDatabase):
        self._database = database

    def rating_for(self, username: str) -> int:
        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT rating FROM accounts WHERE username = %s", (username,)
            ).fetchone()
            return row[0]

    def update_rating(self, username: str, rating: int) -> None:
        with self._database.lock:
            self._database.connection.execute(
                "UPDATE accounts SET rating = %s WHERE username = %s", (rating, username)
            )
            self._database.connection.commit()
