"""The one SQLite connection (+ lock) shared by server/accounts.py's
UserStore and server/rating_store.py's RatingStore - two distinct-
responsibility classes (verifying who you are vs. how good you are) that
happen to read and write the same `accounts` table, the same way the
single AccountStore they replaced did.

A shared connection, not just a shared db_path each store opens for
itself: a ":memory:" SQLite database only exists for the lifetime of the
connection that opened it, so two independent sqlite3.connect(":memory:")
calls would each get their own empty, unrelated database - tests would see
UserStore's freshly-registered rows as if RatingStore's own database had
never heard of them. A real, file-backed db_path doesn't have this
problem (every connection to the same file sees the same data), but using
one shared connection for both stores either way keeps their behavior
identical regardless of which kind of db_path a caller passes, and avoids
opening the same file twice for no benefit.

check_same_thread=False + the shared lock is what then keeps that one
connection safe to call from both the asyncio event-loop thread
(RatingStore's own calls, and UserStore.login's *callers* on the executor
thread - see UserStore's own docstring on why login itself runs there).
"""

import sqlite3
import threading
from dataclasses import dataclass, field


@dataclass
class AccountsDatabase:
    connection: sqlite3.Connection
    lock: threading.RLock = field(default_factory=threading.RLock)


def open_accounts_database(db_path: str) -> AccountsDatabase:
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            username TEXT PRIMARY KEY,
            password_hash BLOB NOT NULL,
            password_salt BLOB NOT NULL,
            rating INTEGER NOT NULL
        )
        """
    )
    connection.commit()
    return AccountsDatabase(connection=connection)
