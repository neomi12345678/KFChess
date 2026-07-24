"""Small Protocol shapes for the handful of GameSession/GameLoop
dependencies worth naming as a contract in their own right, rather than
pinning callers to a concrete class's full surface.

RatingRepository is satisfied by server/rating_store.py's RatingStore
as-is (the two shapes match on purpose - see RatingStore's own docstring)
- naming it here still means GameSession/GameLoop's own constructors
document exactly which two methods they need, without importing
server/rating_store.py just for a type hint. MessageSender is genuinely
narrower than server/connections.py's ConnectionRegistry: GameLoop only
ever broadcasts to already-known usernames/websockets, never set()/
discard_if_current() (server/ws_server.py's own connection-lifecycle
bookkeeping alone, see its _handle_connection/_handle_login) - both
already satisfy these structurally, unchanged.
"""

from typing import Protocol


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
