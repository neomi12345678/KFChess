"""Small Protocol shapes for the handful of GameSession/GameLoop/GameServer
dependencies worth naming as a contract in their own right, rather than
pinning callers to a concrete class's full surface - the same seam that
lets server/postgres/accounts.py's Postgres-backed stores stand in for
server/sqlite/accounts.py's/server/sqlite/rating_store.py's SQLite ones
(see docker-compose.yml) without server/ws_server.py or server/game_loop.py
needing to know which one they were handed.

RatingRepository is satisfied by server/sqlite/rating_store.py's
RatingStore as-is (the two shapes match on purpose - see RatingStore's own
docstring) - naming it here still means GameSession/GameLoop's own
constructors document exactly which two methods they need, without
importing server/sqlite/rating_store.py just for a type hint. MessageSender is genuinely
narrower than server/connections.py's ConnectionRegistry: GameLoop only
ever broadcasts to already-known usernames/websockets, never set()/
discard_if_current() (server/ws_server.py's own connection-lifecycle
bookkeeping alone, see its _handle_connection/_handle_login) - both
already satisfy these structurally, unchanged.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Tuple


# What server/session.py's GameSession actually calls on the rating store
# it's given - see finalize_ratings_if_game_over, the only place a
# GameSession ever touches ratings at all.
class RatingRepository(Protocol):
    def rating_for(self, username: str) -> int: ...

    def update_rating(self, username: str, rating: int) -> None: ...


# What server/game_loop.py's GameLoop actually calls on the
# ConnectionRegistry it's given - broadcasting to already-known usernames/
# websockets, never set()/discard_if_current() (server/ws_server.py's own
# connection-lifecycle bookkeeping alone, see its _handle_connection/
# _handle_login).
class MessageSender(Protocol):
    def get(self, username: str): ...

    async def send(self, websocket, payload) -> None: ...

    async def send_to_username(self, username: str, payload) -> None: ...


# What server/ws_server.py's GameServer actually calls on the user store
# it's given - login (which registers a never-seen username on the spot,
# see server/sqlite/accounts.py's own docstring), raising
# InvalidCredentialsError for a returning username's wrong password.
# Satisfied by server/sqlite/accounts.py's UserStore as-is, and by
# server/postgres/accounts.py's PostgresUserStore.
class UserRepository(Protocol):
    def login(self, username: str, password: str) -> object: ...


# advance_time's own return shape - two lists computed in the same pass over
# waiting entries (see server/matchmaking.py's/server/redis/matchmaking.py's
# own advance_time): timed_out is exactly the old bare List[str] return (who
# just crossed MATCHMAKING_TIMEOUT_MS, already removed from the queue);
# due_for_status is who just crossed a MATCHMAKING_STATUS_INTERVAL_MS notify
# boundary, paired with their own whole-seconds-remaining (the queue is the
# only place holding waited_ms/timeout_ms together, so this is computed
# here, not re-derived by GameLoop with a second call).
@dataclass(frozen=True)
class MatchmakingTick:
    timed_out: List[str]
    due_for_status: List[Tuple[str, int]]


# What server/game_loop.py's GameLoop actually calls on the matchmaking
# queue it owns (self.matchmaking) - satisfied by server/matchmaking.py's
# MatchmakingQueue as-is, and by server/redis/matchmaking.py's
# RedisMatchmakingQueue. All five methods stay synchronous even for the
# Redis-backed implementation - see RedisMatchmakingQueue's own docstring
# for why (server/router.py's CommandRouter, which calls enqueue/remove/
# is_waiting, is deliberately never async).
class MatchmakingQueueProtocol(Protocol):
    def enqueue(self, username: str, rating: int) -> None: ...

    def remove(self, username: str) -> None: ...

    def is_waiting(self, username: str) -> bool: ...

    def advance_time(self, elapsed_ms: int) -> MatchmakingTick: ...

    def find_match(self) -> Optional[Tuple[str, str]]: ...


# What server/game_loop.py's GameLoop actually calls on the lifecycle
# publisher it's given (self._lifecycle_publisher) - two coarse,
# low-volume control-plane events, game-created and game-finished (never
# the per-tick gameplay stream - see server/nats/lifecycle.py's own
# docstring). Satisfied by server/nats/lifecycle.py's
# NatsLifecyclePublisher; GameLoop treats None (the default - see its own
# constructor) as "publish nothing," so this is entirely optional.
class LifecyclePublisher(Protocol):
    async def game_created(
        self, game_id: str, room_id: Optional[str], white_username: str, black_username: str
    ) -> None: ...

    async def game_finished(
        self,
        game_id: str,
        room_id: Optional[str],
        white_username: str,
        black_username: str,
        ratings: Dict[str, int],
    ) -> None: ...


# What server/rooms.py's RoomRegistry and server/game_loop.py's GameLoop
# both call on the "who's currently busy" set they're given - satisfied by
# server/redis/busy_set.py's BusySet. The one piece of PLAY-busy-check
# state (room membership as creator/opponent, or a seated PLAY game) that
# needs to be visible *outside* the process that actually runs games/rooms
# - a standalone api-gateway service can't reach into GameLoop's/
# RoomRegistry's own in-memory state directly, so it reads this instead.
# Optional everywhere it's threaded through (None is a no-op, see
# RoomRegistry's/GameLoop's own constructors) - every existing caller/test
# that omits it keeps today's single-process-only behavior unchanged.
class BusySetProtocol(Protocol):
    def add(self, username: str) -> None: ...

    def remove(self, username: str) -> None: ...

    def contains(self, username: str) -> bool: ...
