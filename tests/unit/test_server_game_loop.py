"""server/game_loop.py's shared tick loop treats a game that raises mid-tick as a
game that just ended abnormally (see GameLoop._fail_game), not a reason to take the
whole tick loop - and thus every other concurrently-running game - down with it.

Also covers GameLoop's own wiring of its optional active_game_index dependency
(see server/interfaces.py's ActiveGameIndexProtocol) - a real, if minimal,
in-memory fake (_FakeActiveGameIndex below), not a mock, the same "real object
standing in for the Redis-backed one" approach every other optional GameLoop
dependency already gets exercised with.

Exercised directly against GameLoop rather than through a full running server (see
tests/integration/test_server_ws.py), since a real GameSession/GameEngine has no dial
to make it misbehave on cue - _CrashingGameSession below is a real GameSession in
every other respect, its tick the one thing overridden.
"""

import asyncio
import contextlib
from typing import Dict, Optional

from boardio.board_parser import parse
from model.piece import BLACK, WHITE
from server.connections import ConnectionRegistry
from server.game_loop import ActiveGame, GameLoop
from server.interfaces import ActiveGameLocation
from server.publisher import NetworkPublisher
from server.rooms import RoomRegistry
from server.session import GameSession
from server.sqlite.accounts import UserStore
from server.sqlite.accounts_db import open_accounts_database
from server.sqlite.rating_store import RatingStore

STARTING_BOARD = "wR . .\n. . .\n. . ."


class _FakeActiveGameIndex:
    def __init__(self):
        self._locations: Dict[str, ActiveGameLocation] = {}

    def set(self, username: str, location: ActiveGameLocation) -> None:
        self._locations[username] = location

    def remove(self, username: str) -> None:
        self._locations.pop(username, None)

    def get(self, username: str) -> Optional[ActiveGameLocation]:
        return self._locations.get(username)


class _CrashingGameSession(GameSession):
    def tick(self, elapsed_ms):
        raise RuntimeError("boom")


def _rating_store():
    database = open_accounts_database(":memory:")
    user_store = UserStore(database)
    for username in ("alice", "bob", "carol", "dave"):
        user_store.login(username, "secret123")
    return RatingStore(database)


def _make_loop(rating_store, rooms=None, active_game_index=None):
    return GameLoop(
        lambda: parse(STARTING_BOARD),
        rating_store,
        rooms if rooms is not None else RoomRegistry(),
        ConnectionRegistry(),
        matchmaking_timeout_ms=60_000,
        disconnect_grace_ms=20_000,
        tick_interval_s=0.01,
        active_game_index=active_game_index,
    )


def test_a_crashing_games_tick_does_not_stop_a_healthy_games_tick():
    async def scenario():
        rating_store = _rating_store()
        loop = _make_loop(rating_store)

        healthy_session = GameSession(parse(STARTING_BOARD), rating_store, "alice", "bob")
        loop._games["healthy"] = ActiveGame(session=healthy_session, publisher=NetworkPublisher(healthy_session.bus))

        crashing_session = _CrashingGameSession(parse(STARTING_BOARD), rating_store, "carol", "dave")
        loop._games["crashing"] = ActiveGame(
            session=crashing_session, publisher=NetworkPublisher(crashing_session.bus)
        )

        task = asyncio.create_task(loop.run_forever())
        await asyncio.sleep(0.05)
        task.cancel()
        # If the crash weren't isolated, run_forever's own task would already have
        # died with the RuntimeError above - suppress only CancelledError here so
        # that (unlikely) failure mode still surfaces as this test erroring out.
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert "crashing" not in loop._games
        assert "healthy" in loop._games

    asyncio.run(scenario())


def test_a_crashing_games_room_is_closed_and_its_seats_are_freed():
    async def scenario():
        rating_store = _rating_store()
        rooms = RoomRegistry()
        room = rooms.create("carol")
        rooms.join(room.room_id, "dave")
        loop = _make_loop(rating_store, rooms)

        crashing_session = _CrashingGameSession(parse(STARTING_BOARD), rating_store, "carol", "dave")
        game = ActiveGame(
            session=crashing_session, publisher=NetworkPublisher(crashing_session.bus), room_id=room.room_id
        )
        loop._games[room.room_id] = game

        await loop._fail_game(room.room_id, game, RuntimeError("boom"))

        assert room.room_id not in loop._games
        assert rooms.room_for_username("carol") is None
        assert rooms.room_for_username("dave") is None

    asyncio.run(scenario())


def test_starting_a_game_records_both_seats_in_the_active_game_index():
    async def scenario():
        rating_store = _rating_store()
        active_game_index = _FakeActiveGameIndex()
        loop = _make_loop(rating_store, active_game_index=active_game_index)

        await loop._start_game("play-1", "alice", "bob")

        assert active_game_index.get("alice") == ActiveGameLocation(game_id="play-1", room_id=None, seat=WHITE)
        assert active_game_index.get("bob") == ActiveGameLocation(game_id="play-1", room_id=None, seat=BLACK)

    asyncio.run(scenario())


def test_starting_a_room_game_records_the_room_id_in_the_active_game_index():
    async def scenario():
        rating_store = _rating_store()
        active_game_index = _FakeActiveGameIndex()
        loop = _make_loop(rating_store, active_game_index=active_game_index)

        await loop._start_game("room-1", "alice", "bob", room_id="room-1")

        assert active_game_index.get("alice") == ActiveGameLocation(game_id="room-1", room_id="room-1", seat=WHITE)

    asyncio.run(scenario())


def test_a_crashing_games_active_game_index_entries_are_removed():
    async def scenario():
        rating_store = _rating_store()
        rooms = RoomRegistry()
        room = rooms.create("carol")
        rooms.join(room.room_id, "dave")
        active_game_index = _FakeActiveGameIndex()
        loop = _make_loop(rating_store, rooms, active_game_index=active_game_index)

        crashing_session = _CrashingGameSession(parse(STARTING_BOARD), rating_store, "carol", "dave")
        game = ActiveGame(
            session=crashing_session, publisher=NetworkPublisher(crashing_session.bus), room_id=room.room_id
        )
        loop._games[room.room_id] = game
        active_game_index.set("carol", ActiveGameLocation(game_id=room.room_id, room_id=room.room_id, seat=WHITE))
        active_game_index.set("dave", ActiveGameLocation(game_id=room.room_id, room_id=room.room_id, seat=BLACK))

        await loop._fail_game(room.room_id, game, RuntimeError("boom"))

        assert active_game_index.get("carol") is None
        assert active_game_index.get("dave") is None

    asyncio.run(scenario())
