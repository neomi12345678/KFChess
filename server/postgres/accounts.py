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
from typing import Optional

import psycopg

from server.accounts import Account, InvalidCredentialsError, _hash_password
from server.postgres import commit_or_rollback, create_table_tolerating_concurrent_creation
from server.server_config import STARTING_RATING


@dataclass
class PostgresAccountsDatabase:
    connection: "psycopg.Connection"
    lock: threading.RLock = field(default_factory=threading.RLock)


def open_postgres_accounts_database(dsn: str) -> PostgresAccountsDatabase:
    connection = psycopg.connect(dsn, autocommit=False)
    # Tolerates the concurrent-first-boot race (see
    # server/postgres/__init__.py's own docstring) - real with two Game
    # Server Shards (docker-compose.yml's game-server/game-server-2) both
    # constructing this store against a freshly initialized, still-empty
    # database at once.
    create_table_tolerating_concurrent_creation(
        connection,
        """
        CREATE TABLE IF NOT EXISTS accounts (
            username TEXT PRIMARY KEY,
            password_hash BYTEA NOT NULL,
            password_salt BYTEA NOT NULL,
            rating INTEGER NOT NULL
        )
        """,
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
            # autocommit=False (see open_postgres_accounts_database) means
            # this SELECT alone opened a transaction that would otherwise
            # stay open - "idle in transaction" server-side - for as long as
            # this connection lives, since a returning user's successful
            # login never reaches _register's own commit(). Left open, it
            # holds a lock that can block an unrelated exclusive operation
            # (e.g. TRUNCATE accounts in a test fixture) indefinitely.
            # row is already a plain fetched tuple, unaffected by this.
            self._database.connection.rollback()

        # Released above, before the deliberately-slow PBKDF2 hash below -
        # holding this lock across it would serialize every concurrent
        # RatingStore call (same connection, same lock) behind however long
        # PASSWORD_HASH_ITERATIONS takes, for a comparison that doesn't
        # touch the connection at all once row is in hand.
        if row is None:
            return self._register(username, password)

        stored_hash, salt = row
        if _hash_password(password, bytes(salt)) != bytes(stored_hash):
            raise InvalidCredentialsError(f"wrong password for '{username}'")

        return Account(username=username)

    def _register(self, username: str, password: str) -> Account:
        salt = os.urandom(16)
        password_hash = _hash_password(password, salt)
        with self._database.lock:
            with commit_or_rollback(self._database.connection):
                self._database.connection.execute(
                    "INSERT INTO accounts (username, password_hash, password_salt, rating) VALUES (%s, %s, %s, %s)",
                    (username, password_hash, salt, STARTING_RATING),
                )
            return Account(username=username)


class PostgresRatingStore:
    """Already matches server/interfaces.py's RatingRepository structurally,
    the same way server/sqlite/rating_store.py's RatingStore does - see its own
    docstring for why every row this reads/writes is assumed to already
    exist (created by PostgresUserStore.login's own INSERT)."""

    def __init__(self, database: PostgresAccountsDatabase):
        self._database = database

    def rating_for(self, username: str) -> int:
        row = self._fetch_row(username)
        return row[0]

    # Same query as rating_for, but None instead of a crash when the row
    # isn't there yet - the one difference services/api_gateway/main.py's
    # own replica-with-primary-fallback rating store (see its own
    # docstring) needs: a *replica*-backed PostgresRatingStore's row can
    # legitimately not exist yet for a brand-new registration (streaming
    # replication lag, however small, is still nonzero) - not the "this
    # should never happen" case rating_for's own row[0] otherwise assumes,
    # which stays true for every caller reading from the primary.
    def rating_for_or_none(self, username: str) -> Optional[int]:
        row = self._fetch_row(username)
        return row[0] if row is not None else None

    def _fetch_row(self, username: str):
        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT rating FROM accounts WHERE username = %s", (username,)
            ).fetchone()
            # Same reasoning as PostgresUserStore.login's own rollback()
            # above - a read-only SELECT under autocommit=False would
            # otherwise leave this connection idle in an open transaction
            # indefinitely (rating_for is called far more often than any
            # write path here, so this is the more consequential of the two).
            self._database.connection.rollback()
            return row

    def update_rating(self, username: str, rating: int) -> None:
        with self._database.lock:
            with commit_or_rollback(self._database.connection):
                self._database.connection.execute(
                    "UPDATE accounts SET rating = %s WHERE username = %s", (rating, username)
                )
