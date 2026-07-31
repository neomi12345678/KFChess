"""Shared login domain types - the parts of "who's logging in" that don't
depend on which backing store actually persists an account: the two
things any UserStore implementation returns/raises (Account,
InvalidCredentialsError - see server/sqlite/accounts.py's UserStore and
server/postgres/accounts.py's PostgresUserStore, chosen between by
server/main.py's _build_stores, gated behind DATABASE_URL), the password
hashing scheme itself (_hash_password), and the session-token scheme
(issue_session_token/verify_session_token) a successful login/identify
uses to prove - rather than just assert - which username a later
IdentifyMessage or api_gateway request belongs to. Kept here rather than
duplicated per backend/service, since both hashing and token
issuance/verification are the security-sensitive part of this - every
caller (server/ws_server.py, services/api_gateway/main.py) imports them
from this single source.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Optional

from server.server_config import PASSWORD_HASH_ITERATIONS, PASSWORD_HASH_NAME


class InvalidCredentialsError(Exception):
    """Raised when a *returning* username's password doesn't match what
    was stored when it was first registered."""


@dataclass(frozen=True)
class Account:
    username: str


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(PASSWORD_HASH_NAME, password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS)


# A stateless, signed session token: proof a username was authenticated
# (LOGIN/POST-login) recently enough to still be trusted, without a
# session table to migrate into either SQLite or Postgres, and without a
# Redis dependency the bare-metal SQLite-only deployment doesn't otherwise
# have - verifying it only needs the shared secret below, not shared
# storage, so it works identically whether one process or many are
# issuing/checking it (see server/server_config.py's SESSION_TOKEN_SECRET/
# SESSION_TOKEN_TTL_S for how that secret is sourced/shared).
#
# expiry is always a bare integer (no ":" in it), so f"{username}:{expiry}"
# can't be reparsed ambiguously regardless of what characters username
# contains - verify_session_token always takes username as a caller-
# supplied parameter, it never extracts one back out of the token itself.
def issue_session_token(username: str, secret: bytes, ttl_s: int) -> str:
    expiry = int(time.time()) + ttl_s
    signature = _sign(username, expiry, secret)
    return f"{expiry}.{signature}"


# False (never a raised exception) for every malformed/expired/tampered
# case alike - this is the one gatekeeper for a session token, and its
# caller (server/ws_server.py's _handle_identify, services/api_gateway/
# main.py's route handlers) always has exactly one thing to do on False:
# reject with Reason.INVALID_SESSION, never branch on why.
def verify_session_token(username: str, token: Optional[str], secret: bytes) -> bool:
    if token is None:
        return False
    expiry_text, _, signature = token.partition(".")
    if not signature:
        return False
    try:
        expiry = int(expiry_text)
    except ValueError:
        return False
    if expiry < int(time.time()):
        return False
    # compare_digest, not ==, so a mismatch takes the same time regardless
    # of how many leading bytes happen to match - a token (unlike the
    # password hashes in server/sqlite/accounts.py's/server/postgres/
    # accounts.py's own login()) is sent on every single request, so it's
    # the more exposed of the two comparisons to a timing attack.
    return hmac.compare_digest(_sign(username, expiry, secret), signature)


def _sign(username: str, expiry: int, secret: bytes) -> str:
    return hmac.new(secret, f"{username}:{expiry}".encode("utf-8"), hashlib.sha256).hexdigest()
