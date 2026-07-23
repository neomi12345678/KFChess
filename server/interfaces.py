"""Small Protocol shapes for the handful of GameSession/GameLoop
dependencies that are genuinely narrower than the concrete class handed to
them - not one per collaborator, just where a caller only ever uses a
couple of methods off an otherwise much bigger class, so its own
constructor should say so rather than pinning callers to the concrete
class's full surface (login()/close()/the sqlite connection it owns, for
AccountStore; set()/discard_if_current(), for ConnectionRegistry).

server/accounts.py's AccountStore and server/connections.py's
ConnectionRegistry already satisfy these structurally, unchanged - nothing
here requires touching either class, only the type hints of the
constructors that only ever need this much of them.
"""

from typing import Protocol


# What server/session.py's GameSession actually calls on the AccountStore
# it's given - see finalize_ratings_if_game_over, the only place a
# GameSession ever touches accounts at all. Never login()/close()/the
# sqlite connection itself - those are server/ws_server.py's and
# server/main.py's concern, not a single in-progress game's.
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
