"""server/game_loop.py's shared tick loop treats a game that raises mid-tick as a
game that just ended abnormally (see GameLoop._fail_game), not a reason to take the
whole tick loop - and thus every other concurrently-running game - down with it.

Exercised directly against GameLoop rather than through a full running server (see
tests/integration/test_server_ws.py), since a real GameSession/GameEngine has no dial
to make it misbehave on cue - _CrashingGameSession below is a real GameSession in
every other respect, its tick the one thing overridden.
"""

import asyncio
import contextlib

from boardio.board_parser import parse
from server.accounts import UserStore
from server.accounts_db import open_accounts_database
from server.connections import ConnectionRegistry
from server.game_loop import ActiveGame, GameLoop
from server.publisher import NetworkPublisher
from server.rating_store import RatingStore
from server.rooms import RoomRegistry
from server.session import GameSession

STARTING_BOARD = "wR . .\n. . .\n. . ."


class _CrashingGameSession(GameSession):
    def tick(self, elapsed_ms):
        raise RuntimeError("boom")


def _rating_store():
    database = open_accounts_database(":memory:")
    user_store = UserStore(database)
    for username in ("alice", "bob", "carol", "dave"):
        user_store.login(username, "secret123")
    return RatingStore(database)


def _make_loop(rating_store, rooms=None):
    return GameLoop(
        lambda: parse(STARTING_BOARD),
        rating_store,
        rooms if rooms is not None else RoomRegistry(),
        ConnectionRegistry(),
        matchmaking_timeout_ms=60_000,
        disconnect_grace_ms=20_000,
        tick_interval_s=0.01,
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
