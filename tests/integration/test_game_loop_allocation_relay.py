"""Real NATS, no mocks - server/game_loop.py's GameLoop.start_game_allocation_relay,
previously with zero test coverage anywhere (neither this nor its own
_on_allocated handler was exercised by any existing test). Written
alongside the shard_address guard fix in _on_allocated: without it, every
shard subscribed to the single global "game.allocated" subject would start
its own redundant copy of every allocated game, regardless of which shard
the Game Allocator actually addressed it to (see that method's own
docstring) - previously silent, since a client always ended up routed to
just one of the copies via ActiveGameIndex's last-write-wins.

Skipped unless KFCHESS_TEST_NATS_URL is set - `docker compose up -d nats` then

    KFCHESS_TEST_NATS_URL=nats://localhost:4222 \
        python -m pytest tests/integration/test_game_loop_allocation_relay.py

so the default `python -m pytest` stays infra-free.
"""

import asyncio
import json
import os

import pytest

from boardio.board_parser import parse
from server.connections import ConnectionRegistry
from server.game_loop import GameLoop
from server.rooms import RoomRegistry
from server.sqlite.accounts import UserStore
from server.sqlite.accounts_db import open_accounts_database
from server.sqlite.rating_store import RatingStore

STARTING_BOARD = "wR . .\n. . .\n. . ."

NATS_URL = os.environ.get("KFCHESS_TEST_NATS_URL")
pytestmark = pytest.mark.skipif(NATS_URL is None, reason="set KFCHESS_TEST_NATS_URL to run these")


def _rating_store():
    database = open_accounts_database(":memory:")
    user_store = UserStore(database)
    for username in ("alice", "bob"):
        user_store.login(username, "secret123")
    return RatingStore(database)


def _make_loop(shard_address):
    return GameLoop(
        lambda: parse(STARTING_BOARD),
        _rating_store(),
        RoomRegistry(),
        ConnectionRegistry(),
        matchmaking_timeout_ms=60_000,
        disconnect_grace_ms=20_000,
        tick_interval_s=0.01,
        shard_address=shard_address,
    )


async def _publish_allocated(game_id, shard_address):
    import nats

    nats_connection = await nats.connect(NATS_URL)
    payload = {
        "game_id": game_id,
        "room_id": None,
        "white_username": "alice",
        "black_username": "bob",
        "shard_address": shard_address,
    }
    await nats_connection.publish("game.allocated", json.dumps(payload).encode("utf-8"))
    await nats_connection.flush()
    await nats_connection.close()


def test_an_allocation_addressed_to_this_shard_starts_the_game():
    async def scenario():
        import nats

        loop = _make_loop(shard_address="shard-a")
        nats_connection = await nats.connect(NATS_URL)
        await loop.start_game_allocation_relay(nats_connection)

        await _publish_allocated("play-addressed-to-me", "shard-a")
        await asyncio.sleep(0.3)

        await nats_connection.close()
        return loop

    loop = asyncio.run(scenario())
    assert loop.get("play-addressed-to-me") is not None


def test_an_allocation_addressed_to_a_different_shard_is_ignored():
    async def scenario():
        import nats

        loop = _make_loop(shard_address="shard-a")
        nats_connection = await nats.connect(NATS_URL)
        await loop.start_game_allocation_relay(nats_connection)

        await _publish_allocated("play-addressed-elsewhere", "shard-b")
        await asyncio.sleep(0.3)

        await nats_connection.close()
        return loop

    loop = asyncio.run(scenario())
    assert loop.get("play-addressed-elsewhere") is None


# No shard_address configured at all (bare-metal-style single-shard setup,
# or a test that never passed one) - the guard must not require it; every
# allocation is accepted unconditionally, matching this GameLoop's own
# pre-guard behavior.
def test_an_allocation_is_accepted_unconditionally_without_a_configured_shard_address():
    async def scenario():
        import nats

        loop = _make_loop(shard_address=None)
        nats_connection = await nats.connect(NATS_URL)
        await loop.start_game_allocation_relay(nats_connection)

        await _publish_allocated("play-no-shard-configured", "shard-b")
        await asyncio.sleep(0.3)

        await nats_connection.close()
        return loop

    loop = asyncio.run(scenario())
    assert loop.get("play-no-shard-configured") is not None
