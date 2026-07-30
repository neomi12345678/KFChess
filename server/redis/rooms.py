"""Redis-backed sibling of server/rooms.py's RoomRegistry, for the standalone
API Gateway (see services/api_gateway/main.py) - same create/join/cancel/
room_for_username surface, same Room/RoomError shapes, just persisted in
Redis instead of an in-process dict, so every API Gateway replica (and,
eventually, whichever Game Server Shard a room gets allocated to - see
services/game_allocator/main.py) sees the same room state instead of each
holding its own.

Room *membership* (creator/opponent/spectators) lives here; which shard
actually hosts the room's live GameSession is a separate concern, decided
once join() below reports the opponent seat just filled (see
services/api_gateway/main.py's own "room.opponent_joined" publish) - this
class never talks to NATS or a shard itself, the same separation of
concerns server/rooms.py's RoomRegistry already draws against
server/game_loop.py's GameLoop.

Redis layout:
    kfchess:room:{room_id}             Hash {creator, opponent}
    kfchess:room:{room_id}:spectators  Set of usernames
    kfchess:room_owner:{username}      room_id the username currently belongs to

HSETNX on the "opponent" field (not a plain read-then-write) is what
decides "first joiner past the creator wins the opponent seat" - the same
"first claim wins, decided atomically in Redis itself" idiom already used
by services/game_allocator/main.py's own _acquire_lease (SET NX) and
server/redis/matchmaking.py's enqueue (HSET's own 1-vs-0 return): a plain
read-modify-write here would let two concurrent joiners both become the
opponent.

Two things this class does that a naive port of server/rooms.py's
RoomRegistry would miss, both required for it to be a real drop-in rather
than a partial one:

- **busy_set** (optional, same server/interfaces.py BusySetProtocol
  server/rooms.py's own RoomRegistry already takes) - without it, a REST
  caller could create/join a room here and *also* queue for PLAY, since
  services/api_gateway/main.py's own _busy_reason has no other way to see
  "this username already has a room." Same "creator/opponent only, never
  a spectator" rule server/redis/busy_set.py's own docstring already
  documents.
- **close(room_id)** - server/rooms.py's RoomRegistry gets cleaned up once
  a room's game ends because GameLoop._advance_game calls close() on the
  exact same RoomRegistry instance it was constructed with. This class is
  a *separate* registry GameLoop never sees, so services/api_gateway/main.py
  calls this instead, from its own game.finished subscription (the same
  event services/persistence_worker/main.py already consumes) - without it,
  every room ever played would leak its Redis keys forever. Best-effort
  only, same as the rest of this pass: this also covers a game that crashes
  mid-tick (see server/game_loop.py's own _fail_game), which publishes
  game.finished with unchanged ratings for exactly this reason - there is
  no separate "crashed" event for this class or persistence-worker to miss.

Plain sync `redis` client, same reasoning as this package's other modules
(server/redis/matchmaking.py, server/redis/busy_set.py,
server/redis/shard_registry.py): every call here is a cheap, local Redis
round-trip from a request handler that isn't otherwise async-bottlenecked.

Note this module lives at server/redis/rooms.py, importing the third-party
`redis` package by its bare top-level name below - Python 3's imports are
absolute by default, so `import redis` here resolves to the installed
library on sys.path, not to this package (server.redis) importing itself.
"""

import uuid
from typing import Optional

import redis

from protocol.types import Reason
from server.interfaces import BusySetProtocol
from server.rooms import Room, RoomError
from server.server_config import ROOM_ID_LENGTH

_ROOM_KEY_PREFIX = "kfchess:room:"
_ROOM_OWNER_KEY_PREFIX = "kfchess:room_owner:"


class RedisRoomRegistry:
    def __init__(self, redis_url: str, busy_set: Optional[BusySetProtocol] = None):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._busy_set = busy_set

    def create(self, username: str) -> Room:
        if self._redis.get(f"{_ROOM_OWNER_KEY_PREFIX}{username}") is not None:
            raise RoomError(Reason.ALREADY_IN_A_ROOM)

        room_id = self._new_id()
        self._redis.hset(f"{_ROOM_KEY_PREFIX}{room_id}", mapping={"creator": username})
        self._redis.set(f"{_ROOM_OWNER_KEY_PREFIX}{username}", room_id)
        if self._busy_set is not None:
            self._busy_set.add(username)
        return Room(room_id=room_id, creator=username)

    # The first join fills the opponent seat; every join after that is a
    # spectator - see this module's own docstring on why hsetnx, not a
    # read-then-write, is what decides that race-safely. Only an opponent
    # (never a spectator) is added to busy_set, matching
    # server/rooms.py's RoomRegistry.join exactly.
    def join(self, room_id: str, username: str) -> Room:
        room_key = f"{_ROOM_KEY_PREFIX}{room_id}"
        if not self._redis.exists(room_key):
            raise RoomError(Reason.ROOM_NOT_FOUND)
        if self._redis.get(f"{_ROOM_OWNER_KEY_PREFIX}{username}") is not None:
            raise RoomError(Reason.ALREADY_IN_A_ROOM)

        became_opponent = self._redis.hsetnx(room_key, "opponent", username)
        if became_opponent:
            if self._busy_set is not None:
                self._busy_set.add(username)
        else:
            self._redis.sadd(f"{room_key}:spectators", username)
        self._redis.set(f"{_ROOM_OWNER_KEY_PREFIX}{username}", room_id)
        return self._load(room_id)

    # Only the creator, and only before an opponent has joined - matches
    # server/rooms.py's RoomRegistry.cancel exactly (see its own docstring
    # for why a started room can't be cancelled, only resigned/disconnected).
    def cancel(self, username: str) -> None:
        room = self.room_for_username(username)
        if room is None:
            raise RoomError(Reason.NOT_IN_A_ROOM)
        if room.creator != username:
            raise RoomError(Reason.NOT_THE_CREATOR)
        if not room.is_pending:
            raise RoomError(Reason.ALREADY_STARTED)

        self._forget(room)

    # Called once the room's own game actually ends (see
    # services/api_gateway/main.py's own game.finished subscription) - the
    # Redis-backed sibling of server/rooms.py's RoomRegistry.close, same
    # "no-op if the room is already gone" tolerance this module's own
    # docstring explains.
    def close(self, room_id: str) -> None:
        room = self._load_if_exists(room_id)
        if room is not None:
            self._forget(room)

    def room_for_username(self, username: str) -> Optional[Room]:
        room_id = self._redis.get(f"{_ROOM_OWNER_KEY_PREFIX}{username}")
        return self._load_if_exists(room_id) if room_id is not None else None

    # A public name for the same lookup close() already does internally -
    # used by services/game_allocator/main.py's own recovery sweep, which
    # only has a room_id (from server/redis/room_shard_index.py's
    # RoomShardIndex) and needs creator/opponent before calling close(),
    # not just a boolean "did it close."
    def room_for_id(self, room_id: str) -> Optional[Room]:
        return self._load_if_exists(room_id)

    def _forget(self, room: Room) -> None:
        room_key = f"{_ROOM_KEY_PREFIX}{room.room_id}"
        self._redis.delete(room_key, f"{room_key}:spectators")
        self._redis.delete(f"{_ROOM_OWNER_KEY_PREFIX}{room.creator}")
        if room.opponent is not None:
            self._redis.delete(f"{_ROOM_OWNER_KEY_PREFIX}{room.opponent}")
        for spectator in room.spectators:
            self._redis.delete(f"{_ROOM_OWNER_KEY_PREFIX}{spectator}")
        if self._busy_set is not None:
            self._busy_set.remove(room.creator)
            if room.opponent is not None:
                self._busy_set.remove(room.opponent)

    def _load_if_exists(self, room_id: str) -> Optional[Room]:
        if not self._redis.exists(f"{_ROOM_KEY_PREFIX}{room_id}"):
            return None
        return self._load(room_id)

    def _load(self, room_id: str) -> Room:
        room_key = f"{_ROOM_KEY_PREFIX}{room_id}"
        fields = self._redis.hgetall(room_key)
        spectators = self._redis.smembers(f"{room_key}:spectators")
        return Room(room_id=room_id, creator=fields["creator"], opponent=fields.get("opponent"), spectators=spectators)

    # Same collision-checked-and-retried approach as server/rooms.py's own
    # RoomRegistry._new_id - a shared, guessable keyspace across every API
    # Gateway replica, not assumed collision-free.
    def _new_id(self) -> str:
        while True:
            candidate = uuid.uuid4().hex[:ROOM_ID_LENGTH]
            if not self._redis.exists(f"{_ROOM_KEY_PREFIX}{candidate}"):
                return candidate
