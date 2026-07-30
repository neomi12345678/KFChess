"""Redis-backed `room_id -> shard_address` lease - the literal
`Server_Design.md` §4 requirement, quoted in full: "room assignment is a
**lease**, not just a registry entry - `SET room:450:owner worker-B NX PX
5000`, renewed by heartbeat while the worker holds the room, released (or
simply expires) on shutdown/crash. A new worker can only take over once the
lease has actually expired, never by just overwriting a live entry." Kept
as its own tiny class rather than folded into server/redis/rooms.py's
RedisRoomRegistry: that module's own docstring already draws the line
between room *membership* (who's in the room) and *which shard hosts the
room's live GameSession*, calling the latter "a separate concern" - this is
that separate concern.

set() is the acquire - NX (only if not already held) + PX (auto-expires),
called once by services/game_allocator/main.py's own _allocate the instant
it decides shard_address for a room_id. renew() is the heartbeat -
server/game_loop.py's own GameLoop._advance_game calls it periodically
(ROOM_LEASE_RENEW_INTERVAL_MS, server/server_config.py) for every room it's
still actively ticking, extending the same PX window - but only if
shard_address still matches the value already stored, via a small Lua
script (EVAL), the same "read-then-write must be atomic or a lease can be
stolen mid-check" reasoning services/game_allocator/main.py's own
_acquire_lease already relies on for NX. Without that atomicity, a lease
that expired half a millisecond before a renew() call could have already
been legitimately re-acquired by a different shard for a *different* game
by the time a plain "GET, then PEXPIRE if it matches" would notice -
EVAL's own single round trip closes that window entirely, since Redis runs
the whole script as one atomic step.

remove() is the release - called both by whichever shard's own GameLoop
just finished the room's game (an ordinary game-over or a same-process
crash - see GameLoop's own _advance_game/_fail_game) and by
services/api_gateway/main.py's own game.finished subscription (see its own
docstring for why it independently needs to, and why calling this twice is
harmless - DEL on an already-gone key is a no-op).

Read by services/api_gateway/main.py (to answer a spectator's REST join
with nothing - see its own docstring for why no lookup is even needed
there) and by services/ws_gateway/main.py (to resolve which shard to relay
a spectator's connection to, per §6.2's "any WS Gateway asks Game Allocator
for the current owner... Spectators do the same").

Deliberately not the same key as services/game_allocator/main.py's own
_acquire_lease (`kfchess:game:{game_id}:owner`) - that key carries a short,
one-shot TTL scoped to the handoff itself (never renewed, and already gone
long before this lease's own PX would first expire), while this one is the
lease that actually lasts for the room's whole lifetime, per §4.

Plain sync `redis` client, same reasoning as this package's other modules
(server/redis/busy_set.py, server/redis/active_game_index.py,
server/redis/shard_registry.py): every call here is a cheap, local Redis
round-trip, not something worth a dedicated async client.

Note this module lives at server/redis/room_shard_index.py, importing the
third-party `redis` package by its bare top-level name below - Python 3's
imports are absolute by default, so `import redis` here resolves to the
installed library on sys.path, not to this package (server.redis)
importing itself.
"""

from typing import List, Optional

import redis

from server.server_config import ROOM_LEASE_TTL_MS

_KEY_PREFIX = "kfchess:room_shard:"

# Atomic "extend the TTL, but only if I'm still the one holding it" - see
# this module's own docstring on why a plain GET-then-PEXPIRE isn't safe.
# KEYS[1]=the room's own key, ARGV[1]=this caller's own shard_address,
# ARGV[2]=the new PX in ms.
_RENEW_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""


class RoomShardIndex:
    def __init__(self, redis_url: str):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._renew_script = self._redis.register_script(_RENEW_SCRIPT)

    # NX+PX acquire - False means some other shard already holds a live
    # (unexpired) lease for this exact room_id, which should never happen
    # in practice (services/game_allocator/main.py's own per-game_id
    # _acquire_lease already serializes allocation of any one room_id to
    # exactly one caller) but is still reported rather than silently
    # overwritten, per §4's own "never by just overwriting a live entry."
    def set(self, room_id: str, shard_address: str, ttl_ms: int = ROOM_LEASE_TTL_MS) -> bool:
        return bool(self._redis.set(f"{_KEY_PREFIX}{room_id}", shard_address, nx=True, px=ttl_ms))

    # The heartbeat - extends the same lease's PX window, but only while
    # shard_address is still the value on file (see this module's own
    # docstring on the Lua script this uses). Returns False if the lease
    # already expired and/or was reassigned to someone else out from under
    # this caller - server/game_loop.py's own _advance_game logs that case
    # rather than treating it as fatal, since the room's own game keeps
    # running in-process either way (this lease is what stops a *new*
    # joiner from being routed elsewhere, not a kill switch on an
    # already-running game).
    def renew(self, room_id: str, shard_address: str, ttl_ms: int = ROOM_LEASE_TTL_MS) -> bool:
        result = self._renew_script(keys=[f"{_KEY_PREFIX}{room_id}"], args=[shard_address, ttl_ms])
        return bool(result)

    def remove(self, room_id: str) -> None:
        self._redis.delete(f"{_KEY_PREFIX}{room_id}")

    def get(self, room_id: str) -> Optional[str]:
        return self._redis.get(f"{_KEY_PREFIX}{room_id}")

    # Every room this index currently maps to a shard - what
    # services/game_allocator/main.py's own recovery sweep iterates to find
    # rooms whose shard has gone quiet (see that module's own docstring).
    # scan_iter (cursor-based SCAN), not KEYS - same reasoning as
    # server/redis/shard_registry.py's own list_live_shards.
    def all_room_ids(self) -> List[str]:
        return [key[len(_KEY_PREFIX):] for key in self._redis.scan_iter(match=f"{_KEY_PREFIX}*")]
