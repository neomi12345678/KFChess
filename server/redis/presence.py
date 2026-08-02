"""Redis-backed "who's currently connected" set - the literal
Server_Design.md §5 requirement ("Presence / session directory | Redis |
Low latency, doesn't need durability beyond a TTL; naturally lives
alongside the room-ownership registry (§4)"). Deliberately narrower than
server/redis/busy_set.py's BusySet: presence answers "does this username
have a live socket open right now, anywhere in the deployment," regardless
of whether they're in a game, in the lobby, or just sitting on the login
screen - not "is this username committed to a game/queue."

Written by whichever process actually terminates the client's socket -
services/ws_gateway/main.py for the Dockerized deployment (see its own
_handle_client, the same lifetime already tracked by
kfchess_ws_gateway_connections), and server/ws_server.py's GameServer for a
bare-metal run (see its own _handle_connection). Both mark a username
online the instant it's known (login/identify) and offline in the same
finally-style cleanup that already exists for connection-registry
bookkeeping - a websocket disconnect is always observed by the same
handler that owns the connection, so mark_offline alone is enough for that
case. What it doesn't cover is the *process* dying (OOM-kill, node
failure) rather than one socket closing - no finally block ever runs for
any of the sockets that process held, so every username it had marked
online would stay stuck forever with no reconciliation path. PRESENCE_TTL_S
(server/server_config.py) is the backstop for exactly that, refreshed on
every mark_online (i.e. every login/identify - see this module's own
docstring above on who calls it) so it never lapses under a genuinely
still-connected username, only a crashed process's stale entries.

services/api_gateway/main.py's GET /presence/{username} is a real reader
of is_online today, not a hypothetical one - the info-leak fix that route
got (checking the requester's own token, never the username being asked
about) was found in the same audit pass that flagged this class's own
missing TTL, which is what makes the backstop above worth having rather
than a purely theoretical gap.

Plain sync `redis` client, same reasoning as this package's other modules.
Note this module lives at server/redis/presence.py, importing the
third-party `redis` package by its bare top-level name below - Python 3's
imports are absolute by default, so `import redis` here resolves to the
installed library on sys.path, not to this package (server.redis)
importing itself.
"""

import redis

from server.server_config import PRESENCE_TTL_S

_ONLINE_KEY_PREFIX = "kfchess:online:"


class Presence:
    def __init__(self, redis_url: str, ttl_s: int = PRESENCE_TTL_S):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._ttl_s = ttl_s

    def mark_online(self, username: str) -> None:
        self._redis.set(f"{_ONLINE_KEY_PREFIX}{username}", "1", ex=self._ttl_s)

    def mark_offline(self, username: str) -> None:
        self._redis.delete(f"{_ONLINE_KEY_PREFIX}{username}")

    def is_online(self, username: str) -> bool:
        return bool(self._redis.exists(f"{_ONLINE_KEY_PREFIX}{username}"))

    # No caller today (see this module's own docstring) - correctness over
    # micro-optimizing a method nothing currently invokes: a per-username
    # key each carrying its own TTL has no single Set left to SCARD in O(1),
    # so this counts by prefix scan instead.
    def online_count(self) -> int:
        return sum(1 for _ in self._redis.scan_iter(match=f"{_ONLINE_KEY_PREFIX}*"))
