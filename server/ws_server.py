"""Single-process WebSocket server: a lobby of logged-in connections, an
ELO-proximity matchmaking queue (see server/matchmaking.py) and an explicit
room registry (see server/rooms.py) as two independent, parallel ways to
start a game, handed off to server/game_loop.py's GameLoop for zero or more
concurrently active GameSessions (see server/session.py) - unlike the
single-game-at-a-time design this replaced, a PLAY match and any number of
rooms can all be running games at once.

GameServer itself is only the connection lifecycle: accept, decode each raw
wire message exactly once via protocol.registry.decode_json_message into
whichever of protocol/lobby_messages.py's/protocol/game_messages.py's
registered dataclasses it is (a LoginMessage, a MoveMessage, ...), hand that
to server/router.py's CommandRouter for the actual routing *decision*, then
perform whatever async work that decision calls for - sending the reply,
and/or awaiting GameLoop.start_room_game. CommandRouter itself is never
async and never touches a websocket, JSON, or a dict - see its own
docstring for why that split exists. The "what's running and how does time
move it forward" logic lives in server/game_loop.py's GameLoop, and every
websocket write goes through server/connections.py's ConnectionRegistry
rather than a raw websocket.send.

Connection lifecycle:
    connect -> LoginMessage(username, password) -> lobby (or straight back
    into an active game's seat, if this username disconnected from it
    within its 20s grace window - see GameSession.mark_disconnected) ->
    either PlayMessage -> queued -> matched into a new game, or
    CreateRoomMessage/JoinRoomMessage -> a room's game once its opponent
    seat fills (see server/rooms.py) -> "matchmaking_timeout" after 60s
    unmatched (see server/matchmaking.py's TIMEOUT_MS).

A disconnect mid-game starts that seat's 20s grace timer (see
server/session.py's DISCONNECT_GRACE_MS); the opponent gets a live
"disconnect_countdown" broadcast, and the disconnected seat auto-resigns
if the window runs out unreconciled. A room's own pending (not yet
started) state is separate from this - its creator can withdraw it
outright with CancelRoomMessage instead.

That 20s grace timer only starts once _handle_connection's own recv loop
actually notices the socket is gone - true immediately for a clean
close (a normal quit), but for a silently dead peer (crashed client, torn
down network) the `websockets` library's own keepalive ping is what
eventually notices, and its stock defaults (ping_interval=20s,
ping_timeout=20s) can take up to ~40s to do so - twice the grace window
this class promises to only start counting once. PING_INTERVAL_S/
PING_TIMEOUT_S below tighten that, so a truly dead connection is always
detected well inside DISCONNECT_GRACE_MS, not after it.
"""

import asyncio
import json
from typing import Callable, Optional

import websockets

from model.board import BoardRepresentation
from protocol.game_messages import ErrorMessage, JumpMessage, MoveMessage
from protocol.lobby_messages import (
    CancelRoomMessage,
    CreateRoomMessage,
    JoinRoomMessage,
    LoginAckMessage,
    LoginMessage,
    PlayMessage,
)
from protocol.registry import message_from_dict
from protocol.types import HOST as DEFAULT_HOST
from protocol.types import PORT as DEFAULT_PORT
from server.accounts import InvalidCredentialsError, UserStore
from server.connections import ConnectionRegistry
from server.game_loop import DEFAULT_TICK_INTERVAL_S, GameLoop
from server.interfaces import RatingRepository
from server.matchmaking import TIMEOUT_MS as MATCHMAKING_TIMEOUT_MS
from server.router import CommandRouter
from server.rooms import RoomRegistry, RoomStore
from server.session import DISCONNECT_GRACE_MS

# Tighter than `websockets`' own 20s/20s stock defaults (see this module's
# own docstring for why a dead connection must be caught faster than
# those), but deliberately not razor-thin: one connection's own abrupt
# close can briefly stall the event loop's ping bookkeeping for every
# *other* connection too (observed up to ~10s on this project's own dev
# setup, cause not fully isolated - a Windows/`websockets` interaction, not
# anything this project's own code controls). Too tight a PING_TIMEOUT_S
# turns that stall into a false-positive keepalive timeout - a cascading
# disconnect for players who were never actually gone - so this stays
# comfortably above it rather than chasing the tightest number that merely
# happens to survive today's specific observation.
PING_INTERVAL_S = 10.0
PING_TIMEOUT_S = 10.0
CLOSE_TIMEOUT_S = 5.0


class GameServer:
    """board_factory is called once per started game (a matched PLAY pair,
    or a room's opponent seat filling) - every new game needs its own fresh
    Board/pieces, not a board reused (and thus stale with a finished game's
    captures) across games.

    port=0 lets the OS assign a free port (see bound_port) - what tests use
    so parallel runs never collide on a fixed port; main.py instead passes
    a fixed, well-known port for a real client to connect to.
    """

    def __init__(
        self,
        board_factory: Callable[[], BoardRepresentation],
        user_store: UserStore,
        rating_store: RatingRepository,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        tick_interval_s: float = DEFAULT_TICK_INTERVAL_S,
        matchmaking_timeout_ms: int = MATCHMAKING_TIMEOUT_MS,
        disconnect_grace_ms: int = DISCONNECT_GRACE_MS,
        ping_interval_s: float = PING_INTERVAL_S,
        ping_timeout_s: float = PING_TIMEOUT_S,
        close_timeout_s: float = CLOSE_TIMEOUT_S,
        room_store: Optional[RoomStore] = None,
    ):
        self._user_store = user_store
        self._rating_store = rating_store
        self._rooms = RoomRegistry(store=room_store)
        self._connections = ConnectionRegistry()
        self._loop = GameLoop(
            board_factory,
            rating_store,
            self._rooms,
            self._connections,
            matchmaking_timeout_ms=matchmaking_timeout_ms,
            disconnect_grace_ms=disconnect_grace_ms,
            tick_interval_s=tick_interval_s,
        )
        self._router = CommandRouter(self._rooms, self._loop, rating_store, self._connections)
        self._host = host
        self._port = port
        self._ping_interval_s = ping_interval_s
        self._ping_timeout_s = ping_timeout_s
        self._close_timeout_s = close_timeout_s
        self._ws_server = None
        self._started = asyncio.Event()

    @property
    def bound_port(self) -> int:
        return self._ws_server.sockets[0].getsockname()[1]

    async def wait_started(self) -> None:
        await self._started.wait()

    async def run_forever(self) -> None:
        async with websockets.serve(
            self._handle_connection,
            self._host,
            self._port,
            ping_interval=self._ping_interval_s,
            ping_timeout=self._ping_timeout_s,
            close_timeout=self._close_timeout_s,
        ) as ws_server:
            self._ws_server = ws_server
            self._started.set()
            await self._loop.run_forever()

    async def _handle_connection(self, websocket) -> None:
        username = None
        try:
            async for message in websocket:
                username = await self._handle_message(websocket, username, message)
        except (websockets.exceptions.ConnectionClosed, OSError):
            # An ordinary disconnect, clean or not (see this module's own
            # docstring on PING_INTERVAL_S/PING_TIMEOUT_S for the "not"
            # case, and ConnectionRegistry.send's own docstring for why
            # OSError - not just ConnectionClosed - needs catching here
            # too) - the finally block below is what actually reacts to it;
            # letting it propagate further would only make `websockets` log
            # it as a spurious "connection handler failed" error, or,
            # uncaught, crash this one connection's task without taking
            # anything else down with it.
            pass
        finally:
            # discard_if_current is False (and every cleanup below skipped)
            # if a newer connection already logged this same username back
            # in - see its own docstring.
            if username is not None and self._connections.discard_if_current(username, websocket):
                self._loop.matchmaking.remove(username)
                game = self._loop.active_game_for(username)
                if game is not None:
                    seat = game.session.seat_for_username(username)
                    if seat is not None:
                        game.session.mark_disconnected(seat)
                    else:
                        game.spectator_usernames.discard(username)
                else:
                    # Only a still-pending room (no opponent yet, so no
                    # GameSession exists for active_game_for to have found
                    # above) can be unwound outright on disconnect - once a
                    # room's game has started, its own seat's disconnect
                    # grace (handled above) is what applies instead.
                    room = self._rooms.room_for_username(username)
                    if room is not None and room.is_pending:
                        self._rooms.cancel(username)

    # Returns the connection's username going forward - unchanged from
    # whatever was passed in, unless this message was the LOGIN that just
    # established it. _handle_connection threads it back in on every call
    # since a plain local variable there can't be updated from in here.
    async def _handle_message(self, websocket, username: Optional[str], message: str) -> Optional[str]:
        try:
            decoded = message_from_dict(json.loads(message))
        except (json.JSONDecodeError, TypeError, KeyError):
            # A malformed message: not valid JSON at all, or a recognized
            # "type" tag whose payload is missing/mistyped a required field
            # (message_from_dict's cls(**kwargs) is what raises TypeError/
            # KeyError for that) - never a message this table simply
            # doesn't recognize, see the `decoded is None` branch below for
            # that case instead.
            await self._connections.send(websocket, ErrorMessage(message=f"malformed message: {message!r}"))
            return username

        # None (an unrecognized "type", or none at all) and a message this
        # method has no case for below (e.g. a client sending one of the
        # server->client-only messages this same registry also decodes,
        # like SeatMessage) are the same "not a message I can act on" fact
        # to the caller - both fall through to the same rejection at the
        # bottom instead of two near-identical branches here.

        if isinstance(decoded, LoginMessage):
            return await self._handle_login(websocket, decoded)

        if username is None:
            await self._connections.send(websocket, ErrorMessage(message="login_required"))
            return username

        if isinstance(decoded, PlayMessage):
            await self._connections.send(websocket, self._router.decide_play(username))
            return username

        if isinstance(decoded, CreateRoomMessage):
            await self._connections.send(websocket, self._router.decide_create_room(username))
            return username

        if isinstance(decoded, CancelRoomMessage):
            await self._connections.send(websocket, self._router.decide_cancel_room(username))
            return username

        if isinstance(decoded, JoinRoomMessage):
            await self._handle_join_room(websocket, username, decoded.room_id)
            return username

        if isinstance(decoded, (MoveMessage, JumpMessage)):
            await self._connections.send(websocket, self._router.decide_game_command(username, decoded))
            return username

        await self._connections.send(websocket, ErrorMessage(message=f"unrecognized message: {message!r}"))
        return username

    async def _handle_login(self, websocket, login_message: LoginMessage) -> Optional[str]:
        # Off the event loop entirely, via the default thread-pool executor
        # - UserStore.login's PBKDF2 hash is real, non-trivial CPU work
        # (see server/accounts.py), and calling it directly here would
        # freeze every other connection's messages and every in-progress
        # game's tick for that long, not just this login (this is also why
        # UserStore itself is safe to call from a different thread - see
        # server/accounts_db.py's own docstring).
        loop = asyncio.get_event_loop()
        try:
            account = await loop.run_in_executor(
                None, self._user_store.login, login_message.username, login_message.password
            )
        except InvalidCredentialsError:
            await self._connections.send(websocket, LoginAckMessage(accepted=False, reason="wrong_password"))
            return None

        username = account.username
        rating = self._rating_store.rating_for(username)

        # A reconnect (or someone just logging the same username in twice)
        # supersedes whatever connection was previously on file - close it
        # proactively rather than leaving it to linger as a zombie until
        # its own client notices or its own keepalive ping eventually times
        # out (see PING_INTERVAL_S/PING_TIMEOUT_S above - by far the slower
        # path). _handle_connection's own finally block already guards
        # against this closing socket evicting the *new* entry we're about
        # to write below (it only clears the registry if its own websocket
        # is still the one on file). Connection registration is this
        # class's own job, not server/router.py's CommandRouter - the same
        # split their own ConnectionLifecycle/ClientMessageRouter draw.
        stale_websocket = self._connections.get(username)
        if stale_websocket is not None and stale_websocket is not websocket:
            asyncio.ensure_future(stale_websocket.close())

        self._connections.set(username, websocket)

        decision = self._router.decide_login(username, rating)
        await self._connections.send(websocket, decision.ack)
        if decision.start_room is not None:
            await self._loop.start_room_game(decision.start_room)
        return username

    async def _handle_join_room(self, websocket, username: str, room_id: str) -> None:
        decision = self._router.decide_join_room(username, room_id)
        await self._connections.send(websocket, decision.ack)
        if decision.start_room is not None:
            await self._loop.start_room_game(decision.start_room)
        elif decision.spectator_snapshot is not None:
            await self._connections.send(websocket, decision.spectator_snapshot)
