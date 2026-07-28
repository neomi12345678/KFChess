"""Shared login domain types - the parts of "who's logging in" that don't
depend on which backing store actually persists an account: the two
things any UserStore implementation returns/raises (Account,
InvalidCredentialsError - see server/sqlite/accounts.py's UserStore and
server/postgres/accounts.py's PostgresUserStore, chosen between by
server/main.py's _build_stores, gated behind DATABASE_URL), and the
password hashing scheme itself (_hash_password). Kept here rather than
duplicated per backend, since hashing is the one part of this that's
actually security-sensitive - both UserStore implementations import it
from this single source.
"""

import hashlib
from dataclasses import dataclass

from server.server_config import PASSWORD_HASH_ITERATIONS, PASSWORD_HASH_NAME


class InvalidCredentialsError(Exception):
    """Raised when a *returning* username's password doesn't match what
    was stored when it was first registered."""


@dataclass(frozen=True)
class Account:
    username: str


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(PASSWORD_HASH_NAME, password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS)
