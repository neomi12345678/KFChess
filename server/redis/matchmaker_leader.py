"""Leader election for the standalone Matchmaker service
(services/matchmaker/main.py) - the fix for the race
server/redis/matchmaking.py's own module docstring describes:
RedisMatchmakingQueue.advance_time/find_match are only safe to call from
one caller at a time, but the whole point of running more than one
Matchmaker replica (k8s/50-matchmaker.yaml) is horizontal scale-out. This
class is what makes the two compatible - every replica still handles its
own share of the matchmaking.requested subscription (enqueue has no shared
counter to race on), but only whichever replica currently holds this lease
actually calls advance_time/find_match each tick; the rest sit out that
part of the loop entirely.

A plain NX+PX acquire-or-renew lease, the same shape as
server/redis/room_shard_index.py's own room-ownership lease and
services/game_allocator/main.py's own _acquire_lease - "only one holder at
a time, self-healing on crash via TTL expiry" is exactly the same property
both of those already need, just applied to "who ticks the matchmaking
queue" instead of "who owns this room."
"""

import uuid

import redis

from server.server_config import MATCHMAKER_LEADER_TTL_MS

_LEADER_KEY = "kfchess:matchmaker:leader"

# Atomic "renew, but only if I'm still the one holding it" - see
# server/redis/room_shard_index.py's own _RENEW_SCRIPT for the identical
# reasoning: a plain GET-then-PEXPIRE isn't atomic, so a lease that expired
# a moment before this call could already have been legitimately
# re-acquired by a different replica by the time a non-atomic check would
# notice, silently extending a lease this instance no longer actually holds.
_RENEW_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""


class MatchmakerLeaderElection:
    def __init__(self, redis_url: str, ttl_ms: int = MATCHMAKER_LEADER_TTL_MS):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._ttl_ms = ttl_ms
        # A random identity per instance (not, say, a hostname) - the only
        # property this needs is "no two live replicas ever generate the
        # same one," which uuid4 already guarantees without depending on
        # the deployment actually giving each replica a distinct hostname.
        self._instance_id = uuid.uuid4().hex
        self._renew_script = self._redis.register_script(_RENEW_SCRIPT)

    # True means this instance is the leader for (at least) the next
    # ttl_ms - either it just acquired a free/expired lease, or it already
    # held the lease and just extended it. False means some other instance
    # currently holds it. Called once per tick (see
    # services/matchmaker/main.py's own _run_forever) - cheap enough
    # (one local Redis round trip, same reasoning as every other
    # per-tick Redis call in this project) to call unconditionally rather
    # than caching a "do I think I'm leader" flag that could drift from
    # what Redis actually holds.
    def acquire_or_renew(self) -> bool:
        if self._redis.set(_LEADER_KEY, self._instance_id, nx=True, px=self._ttl_ms):
            return True
        return bool(self._renew_script(keys=[_LEADER_KEY], args=[self._instance_id, self._ttl_ms]))
