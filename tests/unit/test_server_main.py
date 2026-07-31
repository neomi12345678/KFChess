"""server/main.py's SIGTERM drain handling (_wait_then_drain/
_run_shard_heartbeat) - Server_Design.md §8's own "a Game-Authority pod
being retired stops accepting new rooms, drains its existing ones (bounded
<=90s wait), then exits," previously a known, self-flagged gap
(k8s/70-game-server.yaml's own comment) this pins down.

Exercised against a real GameServer (in-memory SQLite, port=0, same
approach tests/integration/test_server_ws.py's own running_server uses)
with games seeded directly into GameLoop's own _games dict - the same
"reach in directly, no need for a real websocket connection" approach
tests/unit/test_router.py's own _seat_alice_and_bob and
tests/unit/test_server_game_loop.py already use for this exact class.
"""

import asyncio
import contextlib

import pytest

from boardio.board_parser import parse
from server.game_loop import ActiveGame
from server.main import _run_shard_heartbeat, _wait_then_drain
from server.publisher import NetworkPublisher
from server.server_config import MAX_ROOMS_PER_SHARD
from server.session import GameSession
from server.sqlite.accounts import UserStore
from server.sqlite.accounts_db import open_accounts_database
from server.sqlite.rating_store import RatingStore
from server.sqlite.rooms import RoomStore
from server.ws_server import GameServer

STARTING_BOARD = "wR . .\n. . .\n. . ."


@contextlib.asynccontextmanager
async def _running_server():
    accounts_database = open_accounts_database(":memory:")
    server = GameServer(
        lambda: parse(STARTING_BOARD),
        UserStore(accounts_database),
        RatingStore(accounts_database),
        host="localhost",
        port=0,
        tick_interval_s=0.01,
        room_store=RoomStore(":memory:"),
    )
    try:
        yield server
    finally:
        accounts_database.connection.close()


def _seed_one_active_game(server: GameServer, game_id: str = "play-1") -> None:
    session = GameSession(parse(STARTING_BOARD), server._rating_store, "alice", "bob")
    server._loop._games[game_id] = ActiveGame(session=session, publisher=NetworkPublisher(session.bus))


# A real, minimal in-memory fake standing in for
# server/redis/shard_registry.py's ShardRegistry - same "real object, not a
# mock" approach this project's own test suite always uses for an optional
# Redis-backed dependency (see tests/unit/test_server_game_loop.py's
# _FakeActiveGameIndex). Only implements register() - the one method
# _run_shard_heartbeat actually calls.
class _FakeShardRegistry:
    def __init__(self):
        self.reported_room_counts = []

    def register(self, shard_address: str, room_count: int) -> None:
        self.reported_room_counts.append(room_count)


def test_wait_then_drain_returns_immediately_when_no_games_are_active():
    async def scenario():
        async with _running_server() as server:
            run_task = asyncio.create_task(server.run_forever())
            await server.wait_started()
            shutdown_requested = asyncio.Event()
            shutdown_requested.set()

            await asyncio.wait_for(
                _wait_then_drain(
                    server, heartbeat=None, run_task=run_task, shutdown_requested=shutdown_requested, drain_timeout_ms=5000
                ),
                timeout=2.0,
            )

            assert run_task.cancelled()

    asyncio.run(scenario())


def test_wait_then_drain_waits_for_an_active_game_to_finish_before_returning():
    async def scenario():
        async with _running_server() as server:
            run_task = asyncio.create_task(server.run_forever())
            await server.wait_started()
            _seed_one_active_game(server)
            shutdown_requested = asyncio.Event()
            shutdown_requested.set()

            drain_task = asyncio.create_task(
                _wait_then_drain(
                    server, heartbeat=None, run_task=run_task, shutdown_requested=shutdown_requested, drain_timeout_ms=5000
                )
            )
            await asyncio.sleep(0.2)
            assert not drain_task.done()  # still draining - the game is still "active"

            del server._loop._games["play-1"]  # the game finishes naturally

            await asyncio.wait_for(drain_task, timeout=2.0)

    asyncio.run(scenario())


def test_wait_then_drain_times_out_and_exits_anyway_if_a_game_never_finishes():
    async def scenario():
        async with _running_server() as server:
            run_task = asyncio.create_task(server.run_forever())
            await server.wait_started()
            _seed_one_active_game(server)
            shutdown_requested = asyncio.Event()
            shutdown_requested.set()

            await asyncio.wait_for(
                _wait_then_drain(
                    server, heartbeat=None, run_task=run_task, shutdown_requested=shutdown_requested, drain_timeout_ms=200
                ),
                timeout=2.0,
            )

            # Exited anyway, with the game still technically "active" -
            # exactly the bounded-wait contract Server_Design.md §8 asks for.
            assert server.active_game_count() == 1

    asyncio.run(scenario())


def test_wait_then_drain_sets_the_draining_flag_on_the_heartbeat_and_stops_it():
    async def scenario():
        async with _running_server() as server:
            run_task = asyncio.create_task(server.run_forever())
            await server.wait_started()
            shutdown_requested = asyncio.Event()
            shutdown_requested.set()
            draining = asyncio.Event()
            heartbeat_task = asyncio.create_task(asyncio.sleep(1000))  # stands in for the real heartbeat loop

            await asyncio.wait_for(
                _wait_then_drain(
                    server,
                    heartbeat=(heartbeat_task, draining),
                    run_task=run_task,
                    shutdown_requested=shutdown_requested,
                    drain_timeout_ms=200,
                ),
                timeout=2.0,
            )

            assert draining.is_set()
            assert heartbeat_task.cancelled()

    asyncio.run(scenario())


def test_wait_then_drain_reraises_if_run_forever_itself_fails():
    async def scenario():
        async def _broken_run_forever():
            raise RuntimeError("boom")

        run_task = asyncio.create_task(_broken_run_forever())
        shutdown_requested = asyncio.Event()  # never set - run_task must win the race on its own

        # server is never touched on this path (run_task wins the race
        # before active_game_count is ever consulted) - a real GameServer
        # would be unnecessary ceremony here.
        with pytest.raises(RuntimeError, match="boom"):
            await asyncio.wait_for(
                _wait_then_drain(None, heartbeat=None, run_task=run_task, shutdown_requested=shutdown_requested),
                timeout=2.0,
            )

    asyncio.run(scenario())


def test_run_shard_heartbeat_reports_the_real_room_count_until_draining():
    async def scenario():
        registry = _FakeShardRegistry()
        draining = asyncio.Event()
        room_count = 0

        task = asyncio.create_task(
            _run_shard_heartbeat(registry, "shard-a", lambda: room_count, draining, interval_s=0.05)
        )
        try:
            await asyncio.sleep(0.12)
            assert registry.reported_room_counts and all(count == 0 for count in registry.reported_room_counts)

            room_count = 3
            await asyncio.sleep(0.12)
            assert registry.reported_room_counts[-1] == 3

            draining.set()
            await asyncio.sleep(0.12)
            assert registry.reported_room_counts[-1] == MAX_ROOMS_PER_SHARD
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
