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
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Set

from frame_clock import FrameClock
from model.board import BoardRepresentation
from model.piece import BLACK, WHITE
from protocol.game_messages import DisconnectCountdownMessage, ErrorMessage, GameOverMessage, SeatMessage
from protocol.lobby_messages import MatchmakingTimeoutMessage
from protocol.snapshot_codec import panel_to_json, snapshot_to_json
from server.connections import WirePayload
from server.interfaces import MessageSender, RatingRepository
from server.matchmaking import MatchmakingQueue
from server.publisher import NetworkPublisher
from server.rooms import Room, RoomRegistry
from server.session import OTHER_SEAT, GameSession

_logger = logging.getLogger(__name__)

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


# The full per-tick broadcast for one session: its board snapshot plus the
# side-panel move-log/score/names data merged into the same dict (see
# protocol/snapshot_codec.py's own docstring on why panel data is merged
# in rather than a GameSnapshot field). The one place that combines the
# two - every broadcast site (the ordinary tick below, a room's freshly
# reconnected spectators, server/router.py's own one-off spectator-join
# snapshot) needs the exact same payload, just addressed differently.
def full_broadcast_payload(session: GameSession) -> dict:
    payload = snapshot_to_json(session.snapshot())
    payload.update(panel_to_json(session.move_log, session.score, names_for(session)))
    return payload


# One running game plus the server-layer-only facts GameSession itself has
# no business knowing: whether it came from a room at all (room_id is None
# for a PLAY match), who's merely watching it, and the NetworkPublisher
# translating this session's own domain events into wire messages (see
# server/publisher.py - GameSession stays exactly as ignorant of rooms/
# spectators/wire messages as it already is of websockets, see its own
# docstring).
@dataclass
class ActiveGame:
    session: GameSession
    publisher: NetworkPublisher
    room_id: Optional[str] = None
    spectator_usernames: Set[str] = field(default_factory=set)


class GameLoop:
    def __init__(
        self,
        board_factory: Callable[[], BoardRepresentation],
        rating_store: RatingRepository,
        rooms: RoomRegistry,
        connections: MessageSender,
        matchmaking_timeout_ms: int,
        disconnect_grace_ms: int,
        tick_interval_s: float = DEFAULT_TICK_INTERVAL_S,
    ):
        self._board_factory = board_factory
        self._rating_store = rating_store
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
        game = await self._start_game(room.room_id, room.creator, room.opponent, room_id=room.room_id)
        session = game.session

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
                await self._connections.send(spectator_websocket, full_broadcast_payload(session))

    # Uses the same FrameClock play.py's own frame loop does (real elapsed
    # wall-clock time, fractional ms carried into the next tick rather than
    # truncated away) so every networked game's simulated clock keeps the
    # same feel as local play.
    async def run_forever(self) -> None:
        clock = FrameClock()
        while True:
            await asyncio.sleep(self._tick_interval_s)
            whole_ms = clock.tick()

            await self._advance_matchmaking(whole_ms)
            await self._try_start_a_match()

            # list(...) up front - a game finishing mid-loop below mutates
            # self._games (see _advance_game), which would otherwise be
            # unsafe to iterate directly.
            #
            # try/except per game, not around the whole loop - every game
            # shares this one tick task, so an unhandled exception from a
            # single buggy/corrupted GameSession must not take every other
            # concurrently-running game down with it (see _fail_game).
            for game_id, game in list(self._games.items()):
                try:
                    await self._advance_game(game_id, game, whole_ms)
                except Exception as error:
                    await self._fail_game(game_id, game, error)

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

        self._next_play_game_id += 1
        await self._start_game(f"play-{self._next_play_game_id}", white_username, black_username)

    # The one place a GameSession gets built and seated - a PLAY match
    # (white_username/black_username already resolved by matchmaking's own
    # rating-proximity scan) and a room's game (resolved by creator/opponent
    # instead) are both just "two known usernames, ready to start now" by the
    # time either caller gets here; game_id is "play-N" for the former, the
    # room's own room_id for the latter (see this module's own docstring on
    # why games are keyed that way).
    async def _start_game(
        self, game_id: str, white_username: str, black_username: str, room_id: Optional[str] = None
    ) -> ActiveGame:
        session = GameSession(
            self._board_factory(),
            self._rating_store,
            white_username,
            black_username,
            disconnect_grace_ms=self._disconnect_grace_ms,
        )
        game = ActiveGame(session=session, publisher=NetworkPublisher(session.bus), room_id=room_id)
        self._games[game_id] = game

        for seat, username in ((WHITE, white_username), (BLACK, black_username)):
            await self._connections.send_to_username(username, SeatMessage(color=seat))

        return game

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
        for wire_event in game.publisher.drain():
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

        await self._broadcast_to_game(game, full_broadcast_payload(session))

    # Ends `game` the same way a normal game-over does (drop it from
    # self._games, close its room if any) but for an unhandled exception
    # from its own tick instead - the one difference being there's no
    # GameOverMessage/ratings to send, since GameEngine itself never got to
    # decide a winner. Deliberately defensive beyond that: cleanup runs
    # first and unconditionally (pop/close can't themselves raise), and the
    # best-effort notification is wrapped separately so a game whose crash
    # also broke its own broadcast can still be torn down cleanly instead of
    # re-raising out of here and taking the whole tick loop down anyway.
    async def _fail_game(self, game_id: str, game: ActiveGame, error: BaseException) -> None:
        _logger.error("game %s crashed during its tick - ending it", game_id, exc_info=error)

        self._games.pop(game_id, None)
        if game.room_id is not None:
            self._rooms.close(game.room_id)

        try:
            await self._broadcast_to_game(game, ErrorMessage(message="internal_error"))
        except Exception:
            _logger.exception("failed to notify game %s's players about its crash", game_id)

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
