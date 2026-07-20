"""Single-process WebSocket server: a lobby of logged-in connections, an
ELO-proximity matchmaking queue (see server/matchmaking.py) and an explicit
room registry (see server/rooms.py) as two independent, parallel ways to
start a game, and zero or more concurrently active GameSessions (see
server/session.py) - unlike the single-game-at-a-time design this replaced,
a PLAY match and any number of rooms can all be running games at once.

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
import json
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Set

import websockets

from model.board import BoardRepresentation
from model.piece import BLACK, WHITE
from server.accounts import AccountStore, InvalidCredentialsError
from server.matchmaking import TIMEOUT_MS as MATCHMAKING_TIMEOUT_MS
from server.matchmaking import MatchmakingQueue
from server.protocol import (
    ProtocolError,
    is_cancel_room_command,
    is_create_room_command,
    is_play_command,
    panel_to_json,
    parse_command,
    parse_join_room,
    parse_login,
    snapshot_to_json,
)
from server.rooms import Room, RoomError, RoomRegistry
from server.session import DISCONNECT_GRACE_MS, GameSession

DEFAULT_TICK_INTERVAL_S = 0.05

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

_OTHER_SEAT = {WHITE: BLACK, BLACK: WHITE}


# One running game plus the server-layer-only facts GameSession itself has
# no business knowing: whether it came from a room at all (room_id is None
# for a PLAY match), and who's merely watching it. GameSession stays exactly
# as ignorant of rooms/spectators as it already is of websockets - see its
# own docstring.
@dataclass
class _ActiveGame:
    session: GameSession
    room_id: Optional[str] = None
    spectator_usernames: Set[str] = field(default_factory=set)


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
        host: str = "localhost",
        port: int = 8765,
        tick_interval_s: float = DEFAULT_TICK_INTERVAL_S,
        matchmaking_timeout_ms: int = MATCHMAKING_TIMEOUT_MS,
        disconnect_grace_ms: int = DISCONNECT_GRACE_MS,
        ping_interval_s: float = PING_INTERVAL_S,
        ping_timeout_s: float = PING_TIMEOUT_S,
        close_timeout_s: float = CLOSE_TIMEOUT_S,
    ):
        self._board_factory = board_factory
        self._account_store = account_store
        self._matchmaking = MatchmakingQueue(timeout_ms=matchmaking_timeout_ms)
        self._rooms = RoomRegistry()
        self._disconnect_grace_ms = disconnect_grace_ms
        self._games: Dict[str, _ActiveGame] = {}
        self._next_play_game_id = 0
        self._host = host
        self._port = port
        self._tick_interval_s = tick_interval_s
        self._ping_interval_s = ping_interval_s
        self._ping_timeout_s = ping_timeout_s
        self._close_timeout_s = close_timeout_s
        self._connections_by_username: Dict[str, object] = {}
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
            await self._tick_loop()

    async def _handle_connection(self, websocket) -> None:
        username = None
        try:
            async for message in websocket:
                username = await self._handle_message(websocket, username, message)
        except (websockets.exceptions.ConnectionClosed, OSError):
            # An ordinary disconnect, clean or not (see this module's own
            # docstring on PING_INTERVAL_S/PING_TIMEOUT_S for the "not"
            # case, and _safe_send's own docstring for why OSError - not
            # just ConnectionClosed - needs catching here too) - the
            # finally block below is what actually reacts to it; letting it
            # propagate further would only make `websockets` log it as a
            # spurious "connection handler failed" error, or, uncaught,
            # crash this one connection's task without taking anything else
            # down with it (unlike the same gap in _safe_send once did).
            pass
        finally:
            # Only tear down state if this socket is still the one on file
            # for the username - a newer connection may have already logged
            # this same username back in (e.g. a client reconnecting after a
            # network blip before this stale socket's recv loop noticed),
            # and this socket closing later must not evict that live one.
            if username is not None and self._connections_by_username.get(username) is websocket:
                self._connections_by_username.pop(username, None)
                self._matchmaking.remove(username)
                game = self._active_game_for(username)
                if game is not None:
                    seat = game.session.seat_for_username(username)
                    if seat is not None:
                        game.session.mark_disconnected(seat)
                    else:
                        game.spectator_usernames.discard(username)
                else:
                    # Only a still-pending room (no opponent yet, so no
                    # GameSession exists for _active_game_for to have found
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
            await self._safe_send(websocket, {"type": "error", "message": str(error)})
            return username

        if login_request is not None:
            return await self._handle_login(websocket, login_request)

        if username is None:
            await self._safe_send(websocket, {"type": "error", "message": "login_required"})
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
            await self._safe_send(websocket, {"type": "error", "message": str(error)})
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
            await self._safe_send(websocket, {"type": "login_ack", "accepted": False, "reason": "wrong_password"})
            return None

        username = account.username

        # A reconnect (or someone just logging the same username in twice)
        # supersedes whatever connection was previously on file - close it
        # proactively rather than leaving it to linger as a zombie until
        # its own client notices or its own keepalive ping eventually times
        # out (see PING_INTERVAL_S/PING_TIMEOUT_S above - by far the slower
        # path). _handle_connection's own finally block already guards
        # against this closing socket evicting the *new* entry we're about
        # to write below (it only clears self._connections_by_username if
        # its own websocket is still the one on file).
        stale_websocket = self._connections_by_username.get(username)
        if stale_websocket is not None and stale_websocket is not websocket:
            asyncio.ensure_future(stale_websocket.close())

        self._connections_by_username[username] = websocket

        # Reconnecting into an already-active game (within its 20s grace
        # window) takes priority over an ordinary lobby login - the same
        # username is still mid-game, not starting fresh. Applies the same
        # way whether that game came from PLAY or a room - GameSession
        # itself carries no notion of which.
        game = self._active_game_for(username)
        seat = game.session.seat_for_username(username) if game is not None else None
        if seat is not None and game.session.is_disconnected(seat):
            game.session.mark_reconnected(seat)
            await self._safe_send(
                websocket,
                {
                    "type": "login_ack",
                    "accepted": True,
                    "username": username,
                    "rating": account.rating,
                    "reconnected": True,
                    "color": seat,
                },
            )
            return username

        await self._safe_send(
            websocket, {"type": "login_ack", "accepted": True, "username": username, "rating": account.rating}
        )
        return username

    async def _handle_play(self, websocket, username: str) -> None:
        reason = self._busy_reason(username)
        if reason is not None:
            await self._safe_send(websocket, {"type": "play_ack", "accepted": False, "reason": reason})
            return

        rating = self._account_store.rating_for(username)
        self._matchmaking.enqueue(username, rating)
        await self._safe_send(websocket, {"type": "play_ack", "accepted": True, "reason": "queued"})

    async def _handle_create_room(self, websocket, username: str) -> None:
        reason = self._busy_reason(username)
        if reason is not None:
            await self._safe_send(websocket, {"type": "create_room_ack", "accepted": False, "reason": reason})
            return

        room = self._rooms.create(username)
        print(f"[room] '{username}' created room {room.room_id}")
        await self._safe_send(websocket, {"type": "create_room_ack", "accepted": True, "room_id": room.room_id})

    async def _handle_join_room(self, websocket, username: str, room_id: str) -> None:
        reason = self._busy_reason(username)
        if reason is not None:
            await self._safe_send(websocket, {"type": "join_room_ack", "accepted": False, "reason": reason})
            return

        try:
            room = self._rooms.join(room_id, username)
        except RoomError as error:
            await self._safe_send(websocket, {"type": "join_room_ack", "accepted": False, "reason": str(error)})
            return

        role = "opponent" if room.opponent == username else "spectator"
        print(f"[room] '{username}' joined room {room_id} as {role}")
        await self._safe_send(websocket, {"type": "join_room_ack", "accepted": True, "room_id": room_id, "role": role})

        if role == "opponent":
            await self._start_room_game(room)
            return

        # A spectator joining mid-game gets the board as it stands right
        # now - otherwise they'd see nothing at all until the next tick's
        # broadcast happens to land.
        game = self._games.get(room_id)
        if game is not None:
            game.spectator_usernames.add(username)
            payload = snapshot_to_json(game.session.snapshot())
            payload.update(panel_to_json(game.session.move_log, game.session.score))
            await self._safe_send(websocket, payload)

    async def _handle_cancel_room(self, websocket, username: str) -> None:
        try:
            self._rooms.cancel(username)
        except RoomError as error:
            await self._safe_send(websocket, {"type": "cancel_room_ack", "accepted": False, "reason": str(error)})
            return

        print(f"[room] '{username}' cancelled their room")
        await self._safe_send(websocket, {"type": "cancel_room_ack", "accepted": True})

    # Shared by _handle_play/_handle_create_room/_handle_join_room - a
    # connection may only ever be committed to one thing at a time (queued,
    # in a room, or seated/spectating an active game), across both the PLAY
    # and room tracks together, not per-track. None means free to start
    # something new.
    def _busy_reason(self, username: str) -> Optional[str]:
        if self._active_game_for(username) is not None or self._rooms.room_for_username(username) is not None:
            return "already_in_game"
        if self._matchmaking.is_waiting(username):
            return "already_queued"
        return None

    def _active_game_for(self, username: str) -> Optional[_ActiveGame]:
        for game in self._games.values():
            if game.session.seat_for_username(username) is not None or username in game.spectator_usernames:
                return game
        return None

    async def _handle_game_command(self, websocket, username: str, message: str) -> None:
        game = self._active_game_for(username)
        seat = game.session.seat_for_username(username) if game is not None else None
        if seat is None:
            await self._safe_send(websocket, {"type": "ack", "accepted": False, "reason": "not_in_game"})
            return

        try:
            command = parse_command(message, game.session.board_height)
        except ProtocolError as error:
            await self._safe_send(websocket, {"type": "error", "message": str(error)})
            return

        # A connection may only move the color it was seated as - the
        # command's own color letter is otherwise just a client-asserted
        # claim, not something GameEngine checks (see server/session.py).
        if command.color != seat:
            await self._safe_send(websocket, {"type": "ack", "accepted": False, "reason": "wrong_seat"})
            return

        result = game.session.apply_command(command)
        await self._safe_send(websocket, {"type": "ack", "accepted": result.is_accepted, "reason": result.reason})

    # Mirrors play.py's frame loop (real elapsed wall-clock time, fractional
    # ms carried into the next tick rather than truncated away) so every
    # networked game's simulated clock keeps the same feel as local play.
    async def _tick_loop(self) -> None:
        last_tick = time.monotonic()
        carried_ms = 0.0
        while True:
            await asyncio.sleep(self._tick_interval_s)
            now = time.monotonic()
            elapsed_ms = (now - last_tick) * 1000 + carried_ms
            whole_ms = int(elapsed_ms)
            carried_ms = elapsed_ms - whole_ms
            last_tick = now

            await self._advance_matchmaking(whole_ms)
            await self._try_start_a_match()

            # list(...) up front - a game finishing mid-loop below mutates
            # self._games (see _advance_game), which would otherwise be
            # unsafe to iterate directly.
            for game_id, game in list(self._games.items()):
                await self._advance_game(game_id, game, whole_ms)

    async def _advance_matchmaking(self, whole_ms: int) -> None:
        for username in self._matchmaking.advance_time(whole_ms):
            websocket = self._connections_by_username.get(username)
            if websocket is not None:
                await self._safe_send(websocket, {"type": "matchmaking_timeout"})

    async def _try_start_a_match(self) -> None:
        match = self._matchmaking.find_match()
        if match is None:
            return

        white_username, black_username = match
        self._matchmaking.remove(white_username)
        self._matchmaking.remove(black_username)

        session = GameSession(
            self._board_factory(),
            self._account_store,
            white_username,
            black_username,
            disconnect_grace_ms=self._disconnect_grace_ms,
        )
        self._next_play_game_id += 1
        self._games[f"play-{self._next_play_game_id}"] = _ActiveGame(session=session)

        for seat, username in ((WHITE, white_username), (BLACK, black_username)):
            websocket = self._connections_by_username.get(username)
            if websocket is not None:
                await self._safe_send(websocket, {"type": "seat", "color": seat})

    # Called the instant a room's opponent seat fills (see
    # _handle_join_room) rather than waiting for the next tick like
    # _try_start_a_match - a room's pairing is already fully decided by
    # then (create + join, not a rating-proximity scan), so there's nothing
    # left to wait for. Keyed by the room's own id, not a generated one -
    # a room and its game are the same thing from here on (see
    # _advance_game's own room_id-keyed self._rooms.close on game over).
    async def _start_room_game(self, room: Room) -> None:
        session = GameSession(
            self._board_factory(),
            self._account_store,
            room.creator,
            room.opponent,
            disconnect_grace_ms=self._disconnect_grace_ms,
        )
        self._games[room.room_id] = _ActiveGame(session=session, room_id=room.room_id)

        for seat, username in ((WHITE, room.creator), (BLACK, room.opponent)):
            websocket = self._connections_by_username.get(username)
            if websocket is not None:
                await self._safe_send(websocket, {"type": "seat", "color": seat})

    async def _advance_game(self, game_id: str, game: _ActiveGame, whole_ms: int) -> None:
        session = game.session

        expired_seat = session.advance_disconnect_grace(whole_ms)
        if expired_seat is not None:
            session.resign(expired_seat)

        session.tick(whole_ms)

        rating_update = session.finalize_ratings_if_game_over()
        if rating_update is not None:
            await self._broadcast_to_game(game, {"type": "game_over", "ratings": rating_update})
            del self._games[game_id]
            if game.room_id is not None:
                self._rooms.close(game.room_id)
            return

        for seat in (WHITE, BLACK):
            if session.is_disconnected(seat):
                await self._send_to_seat(
                    session,
                    _OTHER_SEAT[seat],
                    {
                        "type": "disconnect_countdown",
                        "seat": seat,
                        "seconds_remaining": session.seconds_remaining_for(seat),
                    },
                )

        payload = snapshot_to_json(session.snapshot())
        payload.update(panel_to_json(session.move_log, session.score))
        await self._broadcast_to_game(game, payload)

    async def _broadcast_to_game(self, game: _ActiveGame, payload: dict) -> None:
        for seat in (WHITE, BLACK):
            await self._send_to_seat(game.session, seat, payload)
        # list(...) - a spectator's connection can drop (and its finally
        # block discard its own username - see _handle_connection) between
        # awaits in this same loop, on a completely different task; mutating
        # the live set mid-iteration would raise RuntimeError.
        for username in list(game.spectator_usernames):
            websocket = self._connections_by_username.get(username)
            if websocket is not None:
                await self._safe_send(websocket, payload)

    async def _send_to_seat(self, session: GameSession, seat: str, payload: dict) -> None:
        websocket = self._connections_by_username.get(session.username_for(seat))
        if websocket is not None:
            await self._safe_send(websocket, payload)

    # Every send in this class goes through here - a connection can drop
    # between us reading self._connections_by_username and actually writing
    # to it (the tick loop and a connection's own recv loop are separate
    # tasks), so every send site would otherwise need its own try/except.
    # Catches OSError alongside websockets' own ConnectionClosed - a socket
    # the OS has already torn down out from under us (observed as a raw
    # ConnectionAbortedError on Windows, not always wrapped into
    # ConnectionClosed by every code path) is exactly as harmless here as
    # an ordinary clean disconnect: this send was going to a connection
    # that's already gone either way. Left uncaught, it used to escape all
    # the way out of the tick loop and crash the *entire* server over one
    # player's dead socket - every other game along with it.
    @staticmethod
    async def _safe_send(websocket, payload: dict) -> None:
        try:
            await websocket.send(json.dumps(payload))
        except (websockets.exceptions.ConnectionClosed, OSError):
            pass
