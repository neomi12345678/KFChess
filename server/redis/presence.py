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
bookkeeping - deterministic add/remove, not a heartbeat-renewed TTL: unlike
server/redis/shard_registry.py's own per-process heartbeat (where "the
process silently died" is exactly the failure this must detect), a
websocket disconnect is always observed by the same handler that owns the
connection, so there's no crash scenario here a TTL would catch that the
deterministic mark_offline call doesn't already cover.

No reader exists yet in this codebase beyond the honest fact of the data
itself - flagged, not hidden, the same way server/redis/busy_set.py's own
docstring flags its own spectator gap: this class exists so the "which
process holds which username's socket" fact used to be only reachable from
its own process, matching §5, but nothing in this project currently reads
is_online for a decision.

Plain sync `redis` client, same reasoning as this package's other modules.
Note this module lives at server/redis/presence.py, importing the
third-party `redis` package by its bare top-level name below - Python 3's
imports are absolute by default, so `import redis` here resolves to the
installed library on sys.path, not to this package (server.redis)
importing itself.
"""

import redis

_ONLINE_KEY = "kfchess:online_usernames"


class Presence:
    def __init__(self, redis_url: str):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    def mark_online(self, username: str) -> None:
        self._redis.sadd(_ONLINE_KEY, username)

    def mark_offline(self, username: str) -> None:
        self._redis.srem(_ONLINE_KEY, username)

    def is_online(self, username: str) -> bool:
        return bool(self._redis.sismember(_ONLINE_KEY, username))

    def online_count(self) -> int:
        return self._redis.scard(_ONLINE_KEY)
