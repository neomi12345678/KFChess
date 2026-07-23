"""Owns every concurrently-active GameSession (a PLAY match or a room's
game), the matchmaking queue that feeds new ones, and the single
authoritative tick that advances all of them each frame - the "what's
running and how does time move it forward" half of what used to be one
GameServer class (server/ws_server.py), split out so connection/lobby-
command handling (still in GameServer) doesn't have to know how a game is
actually ticked, and vice versa.

Games are exposed keyed by id ("play-N" for a PLAY match, or a room's own
room_id) - a room and its game are the same thing once started (see
_advance_game's own self._rooms.close on game over).
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Set

from model.board import BoardRepresentation
from model.piece import BLACK, WHITE
from protocol.game_messages import DisconnectCountdownMessage, GameOverMessage, SeatMessage
from protocol.lobby_messages import MatchmakingTimeoutMessage
from protocol.snapshot_codec import panel_to_json, snapshot_to_json
from server.connections import WirePayload
from server.interfaces import MessageSender, RatingRepository
from server.matchmaking import MatchmakingQueue
from server.rooms import Room, RoomRegistry
from server.session import OTHER_SEAT, GameSession

# Mirrors play.py's frame loop (real elapsed wall-clock time, fractional ms
# carried into the next tick rather than truncated away) so every networked
# game's simulated clock keeps the same feel as local play - see run_forever
# below.
DEFAULT_TICK_INTERVAL_S = 0.05


# {color: username} for panel_to_json's own names argument (see
# protocol/snapshot_codec.py) - both seats' real usernames were already fixed at
# GameSession construction (see server/session.py's own __init__), so this
# is never anything but a real logged-in name, never a "White"/"Black"
# placeholder for a networked game. Not private: server/ws_server.py's own
# _handle_join_room (a spectator joining mid-game) needs the same {color:
# username} shape for its own one-off snapshot send.
def names_for(session: GameSession) -> dict:
    return {WHITE: session.username_for(WHITE), BLACK: session.username_for(BLACK)}


# One running game plus the server-layer-only facts GameSession itself has
# no business knowing: whether it came from a room at all (room_id is None
# for a PLAY match), and who's merely watching it. GameSession stays exactly
# as ignorant of rooms/spectators as it already is of websockets - see its
# own docstring.
@dataclass
class ActiveGame:
    session: GameSession
    room_id: Optional[str] = None
    spectator_usernames: Set[str] = field(default_factory=set)


class GameLoop:
    def __init__(
        self,
        board_factory: Callable[[], BoardRepresentation],
        account_store: RatingRepository,
        rooms: RoomRegistry,
        connections: MessageSender,
        matchmaking_timeout_ms: int,
        disconnect_grace_ms: int,
        tick_interval_s: float = DEFAULT_TICK_INTERVAL_S,
    ):
        self._board_factory = board_factory
        self._account_store = account_store
        self._rooms = rooms
        self._connections = connections
        self.matchmaking = MatchmakingQueue(timeout_ms=matchmaking_timeout_ms)
        self._disconnect_grace_ms = disconnect_grace_ms
        self._tick_interval_s = tick_interval_s
        self._games: Dict[str, ActiveGame] = {}
        self._next_play_game_id = 0

    def get(self, game_id: str) -> Optional[ActiveGame]:
        return self._games.get(game_id)

    def active_game_for(self, username: str) -> Optional[ActiveGame]:
        for game in self._games.values():
            if game.session.seat_for_username(username) is not None or username in game.spectator_usernames:
                return game
        return None

    # Called the instant a room's opponent seat fills (see
    # server/ws_server.py's _handle_join_room, and its _handle_login for the
    # post-restart-reconnect equivalent) rather than waiting for the next
    # tick like _try_start_a_match - a room's pairing is already fully
    # decided by then (create + join, not a rating-proximity scan), so
    # there's nothing left to wait for.
    async def start_room_game(self, room: Room) -> None:
        session = GameSession(
            self._board_factory(),
            self._account_store,
            room.creator,
            room.opponent,
            disconnect_grace_ms=self._disconnect_grace_ms,
        )
        game = ActiveGame(session=session, room_id=room.room_id)
        self._games[room.room_id] = game

        for seat, username in ((WHITE, room.creator), (BLACK, room.opponent)):
            await self._connections.send_to_username(username, SeatMessage(color=seat))

        # Empty in the ordinary "opponent just joined" path - a room only
        # ever gains spectators after it stops being pending (see
        # RoomRegistry.join), so this only ever matters for a room resumed
        # after a server restart (see server/ws_server.py's _handle_login),
        # whose persisted spectators may already be back online by the time
        # this runs.
        for spectator_username in room.spectators:
            spectator_websocket = self._connections.get(spectator_username)
            if spectator_websocket is not None:
                game.spectator_usernames.add(spectator_username)
                payload = snapshot_to_json(session.snapshot())
                payload.update(panel_to_json(session.move_log, session.score, names_for(session)))
                await self._connections.send(spectator_websocket, payload)

    # Mirrors play.py's frame loop (real elapsed wall-clock time, fractional
    # ms carried into the next tick rather than truncated away) so every
    # networked game's simulated clock keeps the same feel as local play.
    async def run_forever(self) -> None:
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
        for username in self.matchmaking.advance_time(whole_ms):
            await self._connections.send_to_username(username, MatchmakingTimeoutMessage())

    async def _try_start_a_match(self) -> None:
        match = self.matchmaking.find_match()
        if match is None:
            return

        white_username, black_username = match
        self.matchmaking.remove(white_username)
        self.matchmaking.remove(black_username)

        session = GameSession(
            self._board_factory(),
            self._account_store,
            white_username,
            black_username,
            disconnect_grace_ms=self._disconnect_grace_ms,
        )
        self._next_play_game_id += 1
        self._games[f"play-{self._next_play_game_id}"] = ActiveGame(session=session)

        for seat, username in ((WHITE, white_username), (BLACK, black_username)):
            await self._connections.send_to_username(username, SeatMessage(color=seat))

    async def _advance_game(self, game_id: str, game: ActiveGame, whole_ms: int) -> None:
        session = game.session

        expired_seat = session.advance_disconnect_grace(whole_ms)
        if expired_seat is not None:
            session.resign(expired_seat)

        session.tick(whole_ms)

        # Sent before the game-over check below, not after - a king-capture
        # ArrivalEvent (and thus its "capture" wire event) is published by
        # the very same tick() call that also ends the game, and a game that
        # just ended returns from this method early (see below) without
        # reaching the ordinary snapshot broadcast at its end.
        for wire_event in session.drain_wire_events():
            await self._broadcast_to_game(game, wire_event)

        rating_update = session.finalize_ratings_if_game_over()
        if rating_update is not None:
            await self._broadcast_to_game(game, GameOverMessage(ratings=rating_update))
            del self._games[game_id]
            if game.room_id is not None:
                self._rooms.close(game.room_id)
            return

        for seat in (WHITE, BLACK):
            if session.is_disconnected(seat):
                await self._connections.send_to_username(
                    session.username_for(OTHER_SEAT[seat]),
                    DisconnectCountdownMessage(seat=seat, seconds_remaining=session.seconds_remaining_for(seat)),
                )

        payload = snapshot_to_json(session.snapshot())
        payload.update(panel_to_json(session.move_log, session.score, names_for(session)))
        await self._broadcast_to_game(game, payload)

    async def _broadcast_to_game(self, game: ActiveGame, payload: WirePayload) -> None:
        for seat in (WHITE, BLACK):
            await self._connections.send_to_username(game.session.username_for(seat), payload)
        # list(...) - a spectator's connection can drop (and its finally
        # block discard its own username - see server/ws_server.py's
        # _handle_connection) between awaits in this same loop, on a
        # completely different task; mutating the live set mid-iteration
        # would raise RuntimeError.
        for username in list(game.spectator_usernames):
            await self._connections.send_to_username(username, payload)
