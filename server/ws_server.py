"""Single-process WebSocket server: a lobby of logged-in connections, an
ELO-proximity matchmaking queue (see server/matchmaking.py) and an explicit
room registry (see server/rooms.py) as two independent, parallel ways to
start a game, handed off to server/game_loop.py's GameLoop for zero or more
concurrently active GameSessions (see server/session.py) - unlike the
single-game-at-a-time design this replaced, a PLAY match and any number of
rooms can all be running games at once.

GameServer itself is only the connection lifecycle (accept, login, clean
disconnect) and the lobby/game command router (PLAY/CREATE_ROOM/JOIN_ROOM/
CANCEL_ROOM, then in-game move/jump commands once seated) - the "what's
running and how does time move it forward" logic lives in
server/game_loop.py's GameLoop, and every websocket write goes through
server/connections.py's ConnectionRegistry rather than a raw
websocket.send. Splitting those out of what used to be one class here is
what keeps this file to "how does a connection's own message get routed",
not also "how does a game tick" or "who do we still have a socket for".

Connection lifecycle:
    connect -> "LOGIN <username> <password>" -> lobby (or straight back
    into an active game's seat, if this username disconnected from it
    within its 20s grace window - see GameSession.mark_disconnected) ->
    either "PLAY" -> queued -> matched into a new game, or "CREATE_ROOM"/
    "JOIN_ROOM <id>" -> a room's game once its opponent seat fills (see
    server/rooms.py) -> "matchmaking_timeout" after 60s unmatched (see
    server/matchmaking.py's TIMEOUT_MS).

A disconnect mid-game starts that seat's 20s grace timer (see
server/session.py's DISCONNECT_GRACE_MS); the opponent gets a live
"disconnect_countdown" broadcast, and the disconnected seat auto-resigns
if the window runs out unreconciled. A room's own pending (not yet
started) state is separate from this - its creator can withdraw it
outright with "CANCEL_ROOM" instead.

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
from typing import Callable, Optional

import websockets

from model.board import BoardRepresentation
from model.piece import BLACK, WHITE
from net_protocol import HOST as DEFAULT_HOST
from net_protocol import PORT as DEFAULT_PORT
from net_protocol import (
    AckMessage,
    CancelRoomAckMessage,
    CreateRoomAckMessage,
    ErrorMessage,
    JoinRoomAckMessage,
    LoginAckMessage,
    PlayAckMessage,
    panel_to_json,
    snapshot_to_json,
)
from server.accounts import AccountStore, InvalidCredentialsError
from server.connections import ConnectionRegistry
from server.game_loop import DEFAULT_TICK_INTERVAL_S, GameLoop, names_for
from server.matchmaking import TIMEOUT_MS as MATCHMAKING_TIMEOUT_MS
from server.protocol import (
    ProtocolError,
    is_cancel_room_command,
    is_create_room_command,
    is_play_command,
    parse_command,
    parse_join_room,
    parse_login,
)
from server.rooms import RoomError, RoomRegistry, RoomStore
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
        account_store: AccountStore,
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
        self._account_store = account_store
        self._rooms = RoomRegistry(store=room_store)
        self._connections = ConnectionRegistry()
        self._loop = GameLoop(
            board_factory,
            account_store,
            self._rooms,
            self._connections,
            matchmaking_timeout_ms=matchmaking_timeout_ms,
            disconnect_grace_ms=disconnect_grace_ms,
            tick_interval_s=tick_interval_s,
        )
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
            login_request = parse_login(message)
        except ProtocolError as error:
            await self._connections.send(websocket, ErrorMessage(message=str(error)))
            return username

        if login_request is not None:
            return await self._handle_login(websocket, login_request)

        if username is None:
            await self._connections.send(websocket, ErrorMessage(message="login_required"))
            return username

        if is_play_command(message):
            await self._handle_play(websocket, username)
            return username

        if is_create_room_command(message):
            await self._handle_create_room(websocket, username)
            return username

        if is_cancel_room_command(message):
            await self._handle_cancel_room(websocket, username)
            return username

        try:
            room_id = parse_join_room(message)
        except ProtocolError as error:
            await self._connections.send(websocket, ErrorMessage(message=str(error)))
            return username
        if room_id is not None:
            await self._handle_join_room(websocket, username, room_id)
            return username

        await self._handle_game_command(websocket, username, message)
        return username

    async def _handle_login(self, websocket, login_request) -> Optional[str]:
        # Off the event loop entirely, via the default thread-pool executor
        # - AccountStore.login's PBKDF2 hash is real, non-trivial CPU work
        # (see server/accounts.py), and calling it directly here would
        # freeze every other connection's messages and every in-progress
        # game's tick for that long, not just this login (this is also why
        # AccountStore itself is safe to call from a different thread - see
        # its own __init__ docstring).
        loop = asyncio.get_event_loop()
        try:
            account = await loop.run_in_executor(
                None, self._account_store.login, login_request.username, login_request.password
            )
        except InvalidCredentialsError:
            await self._connections.send(websocket, LoginAckMessage(accepted=False, reason="wrong_password"))
            return None

        username = account.username

        # A reconnect (or someone just logging the same username in twice)
        # supersedes whatever connection was previously on file - close it
        # proactively rather than leaving it to linger as a zombie until
        # its own client notices or its own keepalive ping eventually times
        # out (see PING_INTERVAL_S/PING_TIMEOUT_S above - by far the slower
        # path). _handle_connection's own finally block already guards
        # against this closing socket evicting the *new* entry we're about
        # to write below (it only clears the registry if its own websocket
        # is still the one on file).
        stale_websocket = self._connections.get(username)
        if stale_websocket is not None and stale_websocket is not websocket:
            asyncio.ensure_future(stale_websocket.close())

        self._connections.set(username, websocket)

        # Reconnecting into an already-active game (within its 20s grace
        # window) takes priority over an ordinary lobby login - the same
        # username is still mid-game, not starting fresh. Applies the same
        # way whether that game came from PLAY or a room - GameSession
        # itself carries no notion of which.
        game = self._loop.active_game_for(username)
        seat = game.session.seat_for_username(username) if game is not None else None
        if seat is not None and game.session.is_disconnected(seat):
            game.session.mark_reconnected(seat)
            await self._connections.send(
                websocket,
                LoginAckMessage(
                    accepted=True, username=username, rating=account.rating, reconnected=True, color=seat
                ),
            )
            return username

        # A room whose opponent seat was already filled before a server
        # restart (see server/rooms.py's RoomStore) has no GameSession to
        # reconnect into above - board state itself is never persisted (see
        # this module's own docstring). Instead, once both the creator and
        # opponent are back online, a fresh game starts for them in the
        # same room, the same way GameLoop.start_room_game already runs the
        # instant the opponent seat first fills. Only a real seat (creator/
        # opponent) triggers this - a spectator's own reconnection is
        # handled once that fresh game actually starts (see
        # GameLoop.start_room_game's own spectator reattachment), not here.
        room = self._rooms.room_for_username(username)
        if room is not None and self._loop.get(room.room_id) is None and username in (room.creator, room.opponent):
            other_username = room.opponent if username == room.creator else room.creator
            seat = WHITE if username == room.creator else BLACK
            if other_username is not None and self._connections.get(other_username) is not None:
                # The other seat is already back online and waiting - start
                # the fresh game now and tell this connection its seat the
                # same way an ordinary mid-game reconnect already does (see
                # above), so play_online.py needs no new message type to
                # understand it.
                await self._loop.start_room_game(room)
                await self._connections.send(
                    websocket,
                    LoginAckMessage(
                        accepted=True, username=username, rating=account.rating, reconnected=True, color=seat
                    ),
                )
                return username

            # First one back - nothing to start yet, just tell the client
            # which room it's waiting to resume (still normally joinable by
            # a new opponent in the meantime if this room never had one -
            # see RoomRegistry.join).
            await self._connections.send(
                websocket,
                LoginAckMessage(accepted=True, username=username, rating=account.rating, resuming_room_id=room.room_id),
            )
            return username

        await self._connections.send(
            websocket, LoginAckMessage(accepted=True, username=username, rating=account.rating)
        )
        return username

    async def _handle_play(self, websocket, username: str) -> None:
        reason = self._busy_reason(username)
        if reason is not None:
            await self._connections.send(websocket, PlayAckMessage(accepted=False, reason=reason))
            return

        rating = self._account_store.rating_for(username)
        self._loop.matchmaking.enqueue(username, rating)
        await self._connections.send(websocket, PlayAckMessage(accepted=True, reason="queued"))

    async def _handle_create_room(self, websocket, username: str) -> None:
        reason = self._busy_reason(username)
        if reason is not None:
            await self._connections.send(websocket, CreateRoomAckMessage(accepted=False, reason=reason))
            return

        room = self._rooms.create(username)
        print(f"[room] '{username}' created room {room.room_id}")
        await self._connections.send(websocket, CreateRoomAckMessage(accepted=True, room_id=room.room_id))

    async def _handle_join_room(self, websocket, username: str, room_id: str) -> None:
        reason = self._busy_reason(username)
        if reason is not None:
            await self._connections.send(websocket, JoinRoomAckMessage(accepted=False, reason=reason))
            return

        try:
            room = self._rooms.join(room_id, username)
        except RoomError as error:
            await self._connections.send(websocket, JoinRoomAckMessage(accepted=False, reason=str(error)))
            return

        role = "opponent" if room.opponent == username else "spectator"
        print(f"[room] '{username}' joined room {room_id} as {role}")
        await self._connections.send(
            websocket, JoinRoomAckMessage(accepted=True, room_id=room_id, role=role)
        )

        if role == "opponent":
            await self._loop.start_room_game(room)
            return

        # A spectator joining mid-game gets the board as it stands right
        # now - otherwise they'd see nothing at all until the next tick's
        # broadcast happens to land.
        game = self._loop.get(room_id)
        if game is not None:
            game.spectator_usernames.add(username)
            payload = snapshot_to_json(game.session.snapshot())
            payload.update(panel_to_json(game.session.move_log, game.session.score, names_for(game.session)))
            await self._connections.send(websocket, payload)

    async def _handle_cancel_room(self, websocket, username: str) -> None:
        try:
            self._rooms.cancel(username)
        except RoomError as error:
            await self._connections.send(websocket, CancelRoomAckMessage(accepted=False, reason=str(error)))
            return

        print(f"[room] '{username}' cancelled their room")
        await self._connections.send(websocket, CancelRoomAckMessage(accepted=True))

    # Shared by _handle_play/_handle_create_room/_handle_join_room - a
    # connection may only ever be committed to one thing at a time (queued,
    # in a room, or seated/spectating an active game), across both the PLAY
    # and room tracks together, not per-track. None means free to start
    # something new.
    def _busy_reason(self, username: str) -> Optional[str]:
        if self._loop.active_game_for(username) is not None or self._rooms.room_for_username(username) is not None:
            return "already_in_game"
        if self._loop.matchmaking.is_waiting(username):
            return "already_queued"
        return None

    async def _handle_game_command(self, websocket, username: str, message: str) -> None:
        game = self._loop.active_game_for(username)
        seat = game.session.seat_for_username(username) if game is not None else None
        if seat is None:
            await self._connections.send(websocket, AckMessage(accepted=False, reason="not_in_game"))
            return

        try:
            command = parse_command(message, game.session.board_height)
        except ProtocolError as error:
            await self._connections.send(websocket, ErrorMessage(message=str(error)))
            return

        # A connection may only move the color it was seated as - the
        # command's own color letter is otherwise just a client-asserted
        # claim, not something GameEngine checks (see server/session.py).
        if command.color != seat:
            await self._connections.send(websocket, AckMessage(accepted=False, reason="wrong_seat"))
            return

        result = game.session.apply_command(command)
        await self._connections.send(websocket, AckMessage(accepted=result.is_accepted, reason=result.reason))
