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
import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Set

from frame_clock import FrameClock
from model.board import BoardStore
from model.piece import BLACK, WHITE
from protocol.game_messages import DisconnectCountdownMessage, ErrorMessage, GameOverMessage, SeatMessage
from protocol.lobby_messages import MatchmakingStatusMessage, MatchmakingTimeoutMessage
from protocol.snapshot_codec import panel_to_json, snapshot_to_json
from server.connections import WirePayload
from server.interfaces import (
    ActiveGameIndexProtocol,
    ActiveGameLocation,
    BusySetProtocol,
    LifecyclePublisher,
    MatchmakingQueueProtocol,
    MessageSender,
    RatingRepository,
)
from server.matchmaking import MatchmakingQueue
from server.publisher import NetworkPublisher
from server.rooms import Room, RoomRegistry
from server.server_config import DEFAULT_TICK_INTERVAL_S, MATCHMAKING_STATUS_INTERVAL_MS
from server.session import OTHER_SEAT, GameSession

_logger = logging.getLogger(__name__)


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
        board_factory: Callable[[], BoardStore],
        rating_store: RatingRepository,
        rooms: RoomRegistry,
        connections: MessageSender,
        matchmaking_timeout_ms: int,
        disconnect_grace_ms: int,
        matchmaking_status_interval_ms: int = MATCHMAKING_STATUS_INTERVAL_MS,
        tick_interval_s: float = DEFAULT_TICK_INTERVAL_S,
        # Overridable so server/main.py can hand in a Redis-backed queue
        # (see server/redis/matchmaking.py, gated behind REDIS_URL) instead
        # of this one-process-only default - every existing caller/test
        # omits this and gets today's behavior unchanged.
        matchmaking: Optional[MatchmakingQueueProtocol] = None,
        # Overridable so server/main.py can hand in a NATS-backed publisher
        # (see server/nats/lifecycle.py, gated behind NATS_URL) for the two
        # coarse game-created/game-finished events below - every existing
        # caller/test omits this and gets today's behavior unchanged (no
        # publish calls at all).
        lifecycle_publisher: Optional[LifecyclePublisher] = None,
        # Overridable so server/main.py can hand in a Redis-backed set (see
        # server/redis/busy_set.py, gated behind REDIS_URL) - a standalone
        # api-gateway's PLAY busy-check reads this instead of reaching into
        # this class's own in-memory self._games. None (the default) is a
        # no-op - every existing caller/test is unaffected.
        busy_set: Optional[BusySetProtocol] = None,
        # Overridable so server/main.py can hand in a Redis-backed index
        # (see server/redis/active_game_index.py, gated behind REDIS_URL) -
        # a standalone api-gateway's POST /login reads this to answer "is
        # this a reconnect, and to which color" without reaching into this
        # class's own in-memory self._games. None (the default) is a no-op
        # - every existing caller/test is unaffected.
        active_game_index: Optional[ActiveGameIndexProtocol] = None,
        # This shard's own address (see server/main.py's SHARD_ADDRESS env
        # var, already used for server/redis/shard_registry.py's own
        # heartbeat) - written into every ActiveGameLocation this class
        # creates, so a standalone WS Gateway (services/ws_gateway/main.py)
        # knows which shard to open its own internal relay connection to.
        # Only meaningful together with active_game_index above (see
        # _start_game's own guard) - every existing caller/test omits both
        # and is unaffected.
        shard_address: Optional[str] = None,
    ):
        self._board_factory = board_factory
        self._rating_store = rating_store
        self._rooms = rooms
        self._connections = connections
        self.matchmaking = matchmaking if matchmaking is not None else MatchmakingQueue(
            timeout_ms=matchmaking_timeout_ms, status_interval_ms=matchmaking_status_interval_ms
        )
        self._disconnect_grace_ms = disconnect_grace_ms
        self._tick_interval_s = tick_interval_s
        self._lifecycle_publisher = lifecycle_publisher
        self._busy_set = busy_set
        self._active_game_index = active_game_index
        self._shard_address = shard_address
        self._games: Dict[str, ActiveGame] = {}
        self._next_play_game_id = 0
        # Flipped by start_matchmaking_relay - see its own docstring for why
        # this must never be True without an active NATS relay subscription
        # already forwarding matchmaking.status/matchmaking.timeout, or
        # waiting players would silently stop hearing anything at all.
        self._matchmaker_is_external = False

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

            # Skipped once a standalone Matchmaker service is doing this
            # polling instead (see start_matchmaking_relay) - running both
            # at once would be two independent consumers racing to
            # find_match()/remove() the same shared Redis-backed queue.
            if not self._matchmaker_is_external:
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

    # Subscribes to the standalone Matchmaker service's matchmaking.status/
    # matchmaking.timeout events (see services/matchmaker/main.py, gated behind
    # EXTERNAL_MATCHMAKER in server/main.py) and forwards them to the named
    # username's live websocket - the exact same wire messages
    # _advance_matchmaking used to compute and send directly, now arriving
    # from a separate process instead, since that process holds no
    # websocket of its own to send anything on. external=True also stops
    # this GameLoop's own local _advance_matchmaking/_try_start_a_match
    # polling (see run_forever's own comment on why running both at once
    # would double-consume the same shared Redis-backed queue).
    async def start_matchmaking_relay(self, nats_connection, external: bool) -> None:
        self._matchmaker_is_external = external

        async def _on_status(msg) -> None:
            payload = json.loads(msg.data)
            await self._connections.send_to_username(
                payload["username"], MatchmakingStatusMessage(seconds_remaining=payload["seconds_remaining"])
            )

        async def _on_timeout(msg) -> None:
            payload = json.loads(msg.data)
            await self._connections.send_to_username(payload["username"], MatchmakingTimeoutMessage())

        await nats_connection.subscribe("matchmaking.status", cb=_on_status)
        await nats_connection.subscribe("matchmaking.timeout", cb=_on_timeout)

    # Subscribes to the standalone Game Allocator service's game.allocated
    # event (see services/game_allocator/main.py) and starts the matched game
    # exactly as _try_start_a_match used to do directly - see
    # start_matched_game. room_id is present for a room allocated this way
    # (services/api_gateway/main.py's handle_join_room -> Game Allocator's
    # own _handle_room_opponent_joined - see that module's docstring) and
    # absent (None) for an ordinary PLAY match, same optional field
    # start_room_game/_start_game already thread through below. Only
    # meaningful once start_matchmaking_relay has set external=True -
    # otherwise this GameLoop is still finding and starting its own matches
    # locally, and nothing ever publishes match.found/room.opponent_joined/
    # game.allocated for this to react to in the first place.
    #
    # game.allocated is a single global NATS subject every shard subscribes
    # to - the payload's own shard_address (already there for
    # services/ws_gateway/main.py's own resolution) is what tells *this*
    # shard whether the event is actually meant for it. Without this guard,
    # every shard in a multi-shard deployment (docker-compose.yml's
    # game-server/game-server-2) would start its own redundant copy of
    # every allocated game - previously-undiscovered, since ActiveGameIndex's
    # last-write-wins always routed clients to exactly one of the copies,
    # leaving the others silently ticking away for nothing.
    async def start_game_allocation_relay(self, nats_connection) -> None:
        async def _on_allocated(msg) -> None:
            payload = json.loads(msg.data)
            if self._shard_address is not None and payload["shard_address"] != self._shard_address:
                return
            await self.start_matched_game(
                payload["game_id"], payload["white_username"], payload["black_username"], room_id=payload.get("room_id")
            )

        await nats_connection.subscribe("game.allocated", cb=_on_allocated)

    # Public wrapper around _start_game for a match allocated by a
    # standalone Game Allocator - the exact same build-GameSession-and-
    # seat-both-players logic _try_start_a_match already calls in-process
    # for a PLAY match (room_id=None), now also reachable from
    # start_game_allocation_relay's subscription for *either* a PLAY match
    # or a room whose opponent seat the standalone API Gateway just filled
    # (room_id set - see this method's own room_id param). Unlike
    # start_room_game, this never re-seats already-persisted spectators -
    # a room reaching here is always freshly started (the API Gateway path
    # publishes room.opponent_joined the instant the opponent joins, never
    # after a restart), so room.spectators is always empty at this point;
    # start_room_game itself is untouched and still owns the post-restart-
    # resume case (see server/router.py's decide_login).
    async def start_matched_game(
        self, game_id: str, white_username: str, black_username: str, room_id: Optional[str] = None
    ) -> ActiveGame:
        return await self._start_game(game_id, white_username, black_username, room_id=room_id)

    async def _advance_matchmaking(self, whole_ms: int) -> None:
        tick = self.matchmaking.advance_time(whole_ms)
        for username in tick.timed_out:
            await self._connections.send_to_username(username, MatchmakingTimeoutMessage())
        for username, seconds_remaining in tick.due_for_status:
            await self._connections.send_to_username(
                username, MatchmakingStatusMessage(seconds_remaining=seconds_remaining)
            )

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

        if self._busy_set is not None:
            self._busy_set.add(white_username)
            self._busy_set.add(black_username)

        if self._active_game_index is not None and self._shard_address is not None:
            self._active_game_index.set(white_username, ActiveGameLocation(game_id, room_id, WHITE, self._shard_address))
            self._active_game_index.set(black_username, ActiveGameLocation(game_id, room_id, BLACK, self._shard_address))

        if self._lifecycle_publisher is not None:
            await self._lifecycle_publisher.game_created(game_id, room_id, white_username, black_username)

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
            if self._lifecycle_publisher is not None:
                await self._lifecycle_publisher.game_finished(
                    game_id, game.room_id, session.username_for(WHITE), session.username_for(BLACK), rating_update
                )
            if self._busy_set is not None:
                self._busy_set.remove(session.username_for(WHITE))
                self._busy_set.remove(session.username_for(BLACK))
            if self._active_game_index is not None:
                self._active_game_index.remove(session.username_for(WHITE))
                self._active_game_index.remove(session.username_for(BLACK))
            del self._games[game_id]
            if game.room_id is not None:
                self._rooms.close(game.room_id)
            return

        for seat in (WHITE, BLACK):
            seconds_remaining = session.seconds_remaining_for(seat)
            if seconds_remaining is not None:
                await self._connections.send_to_username(
                    session.username_for(OTHER_SEAT[seat]),
                    DisconnectCountdownMessage(seat=seat, seconds_remaining=seconds_remaining),
                )

        await self._broadcast_to_game(game, full_broadcast_payload(session))

    # Ends `game` the same way a normal game-over does (drop it from
    # self._games, close its room if any) but for an unhandled exception
    # from its own tick instead - the one difference being there's no
    # GameOverMessage/ratings *update* to send, since GameEngine itself
    # never got to decide a winner (see the unchanged ratings publish
    # below, not a call to finalize_ratings_if_game_over). Deliberately
    # defensive beyond that: cleanup runs first and unconditionally
    # (pop/close can't themselves raise), and every best-effort
    # notification after it is wrapped separately so a game whose crash
    # also broke its own broadcast, or a lifecycle publish that fails, can
    # still be torn down cleanly instead of re-raising out of here and
    # taking the whole tick loop down anyway.
    async def _fail_game(self, game_id: str, game: ActiveGame, error: BaseException) -> None:
        _logger.error("game %s crashed during its tick - ending it", game_id, exc_info=error)

        white_username = game.session.username_for(WHITE)
        black_username = game.session.username_for(BLACK)

        self._games.pop(game_id, None)
        if self._busy_set is not None:
            self._busy_set.remove(white_username)
            self._busy_set.remove(black_username)
        if self._active_game_index is not None:
            self._active_game_index.remove(white_username)
            self._active_game_index.remove(black_username)
        if game.room_id is not None:
            self._rooms.close(game.room_id)

        # Publishes game.finished the same as an ordinary game-over
        # (unchanged ratings, since no winner was ever decided) so the
        # standalone Persistence Worker still records this game and a
        # standalone API Gateway's own RedisRoomRegistry still cleans up
        # this room's Redis keys - both previously only reachable from
        # _advance_game's own game-over path, leaving a crashed game's
        # history unwritten and its room's Redis keys leaked forever (see
        # server/redis/rooms.py's own close() docstring, now fixed).
        if self._lifecycle_publisher is not None:
            try:
                ratings = {
                    WHITE: self._rating_store.rating_for(white_username),
                    BLACK: self._rating_store.rating_for(black_username),
                }
                await self._lifecycle_publisher.game_finished(
                    game_id, game.room_id, white_username, black_username, ratings
                )
            except Exception:
                _logger.exception("failed to publish game.finished for crashed game %s", game_id)

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
