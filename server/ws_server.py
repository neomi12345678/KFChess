"""Single-process WebSocket server: a lobby of logged-in connections, an
ELO-proximity matchmaking queue (see server/matchmaking.py), and at most one
active GameSession (see server/session.py) at a time - a new pair is
matched and a fresh game started only once the previous one has ended, so
the server serves a sequence of games over its lifetime, not just one.

Connection lifecycle:
    connect -> "LOGIN <username> <password>" -> lobby (or straight back
    into an active game's seat, if this username disconnected from it
    within its 20s grace window - see GameSession.mark_disconnected) ->
    "PLAY" -> queued -> matched into a new game, or "matchmaking_timeout"
    after 60s unmatched (see server/matchmaking.py's TIMEOUT_MS).

A disconnect mid-game starts that seat's 20s grace timer (see
server/session.py's DISCONNECT_GRACE_MS); the opponent gets a live
"disconnect_countdown" broadcast, and the disconnected seat auto-resigns
if the window runs out unreconciled.
"""

import asyncio
import json
import time
from typing import Callable, Dict, Optional

import websockets

from model.board import BoardRepresentation
from model.piece import BLACK, WHITE
from server.accounts import AccountStore, InvalidCredentialsError
from server.matchmaking import TIMEOUT_MS as MATCHMAKING_TIMEOUT_MS
from server.matchmaking import MatchmakingQueue
from server.protocol import ProtocolError, is_play_command, parse_command, parse_login, snapshot_to_json
from server.session import DISCONNECT_GRACE_MS, GameSession

DEFAULT_TICK_INTERVAL_S = 0.05
_OTHER_SEAT = {WHITE: BLACK, BLACK: WHITE}


class GameServer:
    """board_factory is called once per matched pair (see server/main.py) -
    every new game needs its own fresh Board/pieces, not a board reused
    (and thus stale with a finished game's captures) across games.

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
    ):
        self._board_factory = board_factory
        self._account_store = account_store
        self._matchmaking = MatchmakingQueue(timeout_ms=matchmaking_timeout_ms)
        self._disconnect_grace_ms = disconnect_grace_ms
        self.current_game: Optional[GameSession] = None
        self._host = host
        self._port = port
        self._tick_interval_s = tick_interval_s
        self._connections_by_username: Dict[str, object] = {}
        self._ws_server = None
        self._started = asyncio.Event()

    @property
    def bound_port(self) -> int:
        return self._ws_server.sockets[0].getsockname()[1]

    async def wait_started(self) -> None:
        await self._started.wait()

    async def run_forever(self) -> None:
        async with websockets.serve(self._handle_connection, self._host, self._port) as ws_server:
            self._ws_server = ws_server
            self._started.set()
            await self._tick_loop()

    async def _handle_connection(self, websocket) -> None:
        username = None
        try:
            async for message in websocket:
                username = await self._handle_message(websocket, username, message)
        finally:
            if username is not None:
                self._connections_by_username.pop(username, None)
                self._matchmaking.remove(username)
                if self.current_game is not None:
                    seat = self.current_game.seat_for_username(username)
                    if seat is not None:
                        self.current_game.mark_disconnected(seat)

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

        await self._handle_game_command(websocket, username, message)
        return username

    async def _handle_login(self, websocket, login_request) -> Optional[str]:
        try:
            account = self._account_store.login(login_request.username, login_request.password)
        except InvalidCredentialsError:
            await self._safe_send(websocket, {"type": "login_ack", "accepted": False, "reason": "wrong_password"})
            return None

        username = account.username
        self._connections_by_username[username] = websocket

        # Reconnecting into an already-active game (within its 20s grace
        # window) takes priority over an ordinary lobby login - the same
        # username is still mid-game, not starting fresh.
        seat = self.current_game.seat_for_username(username) if self.current_game is not None else None
        if seat is not None and self.current_game.is_disconnected(seat):
            self.current_game.mark_reconnected(seat)
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
        if self.current_game is not None and self.current_game.seat_for_username(username) is not None:
            await self._safe_send(websocket, {"type": "play_ack", "accepted": False, "reason": "already_in_game"})
            return

        if self._matchmaking.is_waiting(username):
            await self._safe_send(websocket, {"type": "play_ack", "accepted": False, "reason": "already_queued"})
            return

        rating = self._account_store.rating_for(username)
        self._matchmaking.enqueue(username, rating)
        await self._safe_send(websocket, {"type": "play_ack", "accepted": True, "reason": "queued"})

    async def _handle_game_command(self, websocket, username: str, message: str) -> None:
        seat = self.current_game.seat_for_username(username) if self.current_game is not None else None
        if seat is None:
            await self._safe_send(websocket, {"type": "ack", "accepted": False, "reason": "not_in_game"})
            return

        try:
            command = parse_command(message, self.current_game.board_height)
        except ProtocolError as error:
            await self._safe_send(websocket, {"type": "error", "message": str(error)})
            return

        # A connection may only move the color it was seated as - the
        # command's own color letter is otherwise just a client-asserted
        # claim, not something GameEngine checks (see server/session.py).
        if command.color != seat:
            await self._safe_send(websocket, {"type": "ack", "accepted": False, "reason": "wrong_seat"})
            return

        result = self.current_game.apply_command(command)
        await self._safe_send(websocket, {"type": "ack", "accepted": result.is_accepted, "reason": result.reason})

    # Mirrors play.py's frame loop (real elapsed wall-clock time, fractional
    # ms carried into the next tick rather than truncated away) so the
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

            if self.current_game is not None:
                await self._advance_current_game(whole_ms)
            else:
                await self._try_start_a_match()

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

        self.current_game = GameSession(
            self._board_factory(),
            self._account_store,
            white_username,
            black_username,
            disconnect_grace_ms=self._disconnect_grace_ms,
        )

        for seat, username in ((WHITE, white_username), (BLACK, black_username)):
            websocket = self._connections_by_username.get(username)
            if websocket is not None:
                await self._safe_send(websocket, {"type": "seat", "color": seat})

    async def _advance_current_game(self, whole_ms: int) -> None:
        game = self.current_game

        expired_seat = game.advance_disconnect_grace(whole_ms)
        if expired_seat is not None:
            game.resign(expired_seat)

        game.tick(whole_ms)

        rating_update = game.finalize_ratings_if_game_over()
        if rating_update is not None:
            await self._broadcast_to_game(game, {"type": "game_over", "ratings": rating_update})
            self.current_game = None
            return

        for seat in (WHITE, BLACK):
            if game.is_disconnected(seat):
                await self._send_to_seat(
                    game,
                    _OTHER_SEAT[seat],
                    {
                        "type": "disconnect_countdown",
                        "seat": seat,
                        "seconds_remaining": game.seconds_remaining_for(seat),
                    },
                )

        await self._broadcast_to_game(game, snapshot_to_json(game.snapshot()))

    async def _broadcast_to_game(self, game: GameSession, payload: dict) -> None:
        for seat in (WHITE, BLACK):
            await self._send_to_seat(game, seat, payload)

    async def _send_to_seat(self, game: GameSession, seat: str, payload: dict) -> None:
        websocket = self._connections_by_username.get(game.username_for(seat))
        if websocket is not None:
            await self._safe_send(websocket, payload)

    # Every send in this class goes through here - a connection can drop
    # between us reading self._connections_by_username and actually writing
    # to it (the tick loop and a connection's own recv loop are separate
    # tasks), so every send site would otherwise need its own try/except.
    @staticmethod
    async def _safe_send(websocket, payload: dict) -> None:
        try:
            await websocket.send(json.dumps(payload))
        except websockets.exceptions.ConnectionClosed:
            pass
