"""Real GameServer (standing in for a Game Server Shard), real
services/ws_gateway/main.py relay logic, real Redis, real NATS, real raw
websocket clients - no mocks. Exercises services/ws_gateway/main.py's own
_handle_client directly (via a plain websockets.serve, the same way
tests/integration/test_server_ws.py exercises GameServer directly) rather
than spawning the real services.ws_gateway.main.main() OS process, so the
shard's own dynamically-assigned bound_port (port=0, same reasoning as
every other test in this project using a real socket) can be threaded
straight into the gateway as shard_port, no fixed-port collision risk.

Skipped unless KFCHESS_TEST_REDIS_URL and KFCHESS_TEST_NATS_URL are set:

    docker compose up -d redis nats
    KFCHESS_TEST_REDIS_URL=redis://localhost:6379/0 \
    KFCHESS_TEST_NATS_URL=nats://localhost:4222 \
        python -m pytest tests/integration/test_ws_gateway.py

so the default `python -m pytest` stays infra-free.
"""

import asyncio
import contextlib
import json
import os

import pytest
import websockets

from boardio.algebraic_notation import parse_square
from boardio.board_parser import parse
from model.piece import WHITE
from protocol.game_messages import build_move
from protocol.lobby_messages import IdentifyMessage
from protocol.registry import encode_json_message
from server.interfaces import ActiveGameLocation
from server.redis.active_game_index import ActiveGameIndex
from server.redis.room_shard_index import RoomShardIndex
from server.redis.rooms import RedisRoomRegistry
from server.sqlite.accounts import UserStore
from server.sqlite.accounts_db import open_accounts_database
from server.sqlite.rating_store import RatingStore
from server.ws_server import GameServer
from services.ws_gateway.main import _AllocationWaiters, _handle_client, _StatusRelay, _subscribe_matchmaking_events

STARTING_BOARD = "wR . .\n. . .\n. . ."
SHARD_ADDRESS = "localhost"

REDIS_URL = os.environ.get("KFCHESS_TEST_REDIS_URL")
NATS_URL = os.environ.get("KFCHESS_TEST_NATS_URL")
pytestmark = pytest.mark.skipif(
    REDIS_URL is None or NATS_URL is None,
    reason="set KFCHESS_TEST_REDIS_URL and KFCHESS_TEST_NATS_URL to run these",
)


@contextlib.asynccontextmanager
async def running_shard():
    accounts_database = open_accounts_database(":memory:")
    server = GameServer(
        lambda: parse(STARTING_BOARD),
        UserStore(accounts_database),
        RatingStore(accounts_database),
        host="localhost",
        port=0,
        tick_interval_s=0.01,
        # Real, read-only cross-process room lookup (see server/router.py's
        # decide_identify) - harmless for every other test in this file
        # (they never reach the spectator self-heal branch, since their own
        # usernames are always found as seated players first), and required
        # by the spectator test below.
        remote_rooms=RedisRoomRegistry(REDIS_URL),
    )
    task = asyncio.create_task(server.run_forever())
    await server.wait_started()
    try:
        yield server
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        accounts_database.connection.close()


@contextlib.asynccontextmanager
async def running_ws_gateway(shard_port: int):
    import nats

    active_game_index = ActiveGameIndex(REDIS_URL)
    rooms = RedisRoomRegistry(REDIS_URL)
    room_shard_index = RoomShardIndex(REDIS_URL)
    waiters = _AllocationWaiters()
    status_relay = _StatusRelay()
    nats_connection = await nats.connect(NATS_URL)
    await _subscribe_matchmaking_events(nats_connection, waiters, status_relay)

    async def _handler(client_ws) -> None:
        await _handle_client(active_game_index, rooms, room_shard_index, waiters, status_relay, shard_port, client_ws)

    async with websockets.serve(_handler, "localhost", 0) as gw_server:
        port = gw_server.sockets[0].getsockname()[1]
        try:
            yield port
        finally:
            await nats_connection.close()


async def recv_of_type(websocket, message_type: str, timeout: float = 3.0) -> dict:
    while True:
        message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=timeout))
        if message.get("type") == message_type:
            return message


async def send_move(websocket, color: str, source: str, destination: str, board_height: int) -> None:
    message = build_move(color, parse_square(source, board_height), parse_square(destination, board_height))
    await websocket.send(encode_json_message(message))


@pytest.fixture
def clean_active_game_index():
    import redis as redis_lib

    redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    for key in redis_client.scan_iter(match="kfchess:active_game:*"):
        redis_client.delete(key)


@pytest.fixture
def clean_room_state():
    import redis as redis_lib

    redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    for pattern in ("kfchess:room:*", "kfchess:room_owner:*", "kfchess:room_shard:*"):
        for key in redis_client.scan_iter(match=pattern):
            redis_client.delete(key)


def test_identify_for_an_already_allocated_username_relays_moves(clean_active_game_index):
    async def scenario():
        async with running_shard() as server:
            # Seeds a real game directly on the shard, the same way
            # tests/unit/test_server_game_loop.py reaches into GameLoop
            # rather than going through matchmaking/rooms - this test is
            # about the relay, not about how a game gets started.
            #
            # Deliberately *before* the client ever connects/identifies -
            # _start_game's own one-shot SeatMessage broadcast has nobody
            # registered to reach yet and is silently lost (this is exactly
            # the real race a live docker-compose run surfaced: WS Gateway's
            # own internal IDENTIFY handshake can lag behind the shard
            # already having started the game via the same game.allocated
            # event). decide_identify's own re-send (see server/router.py)
            # is what's actually being proven below - not just that a later
            # MOVE happens to work.
            await server._loop._start_game("play-test", "gw_alice", "gw_bob")

            ActiveGameIndex(REDIS_URL).set(
                "gw_alice",
                ActiveGameLocation(game_id="play-test", room_id=None, seat=WHITE, shard_address=SHARD_ADDRESS),
            )

            async with running_ws_gateway(shard_port=server.bound_port) as gw_port:
                async with websockets.connect(f"ws://localhost:{gw_port}") as client:
                    await client.send(encode_json_message(IdentifyMessage(username="gw_alice")))

                    # Proves _relay's own internal handshake frame (the
                    # shard's IdentifyAckMessage) actually reaches the public
                    # client instead of being silently swallowed - a real
                    # client (client/network_client.py's own login()) waits
                    # on exactly this after sending IdentifyMessage.
                    identify_ack = await recv_of_type(client, "identify_ack")
                    assert identify_ack == {"type": "identify_ack", "accepted": True}

                    # Proves decide_identify's own resend, not the original
                    # (already-missed) broadcast from _start_game above.
                    seat = await recv_of_type(client, "seat")
                    assert seat == {"type": "seat", "color": "white"}

                    await send_move(client, WHITE, "a1", "a2", board_height=3)
                    ack = await recv_of_type(client, "ack")
                    assert ack["reason"] != "not_in_game"

    asyncio.run(scenario())


def test_identify_before_allocation_waits_for_game_allocated(clean_active_game_index):
    async def scenario():
        import nats

        async with running_shard() as server:
            async with running_ws_gateway(shard_port=server.bound_port) as gw_port:
                async with websockets.connect(f"ws://localhost:{gw_port}") as client:
                    await client.send(encode_json_message(IdentifyMessage(username="gw_carol")))
                    # Gives _handle_client time to reach _resolve_shard's own
                    # waiters.wait_for("gw_carol") before this test publishes
                    # game.allocated - same reasoning as this project's other
                    # NATS-timing tests (see tests/integration/test_api_gateway.py).
                    await asyncio.sleep(0.2)

                    await server._loop._start_game("play-test-2", "gw_carol", "gw_dave")
                    nats_connection = await nats.connect(NATS_URL)
                    payload = {
                        "game_id": "play-test-2",
                        "room_id": None,
                        "white_username": "gw_carol",
                        "black_username": "gw_dave",
                        "shard_address": SHARD_ADDRESS,
                    }
                    await nats_connection.publish("game.allocated", json.dumps(payload).encode("utf-8"))
                    await nats_connection.flush()
                    await nats_connection.close()

                    await send_move(client, WHITE, "a1", "a2", board_height=3)
                    ack = await recv_of_type(client, "ack")
                    assert ack["reason"] != "not_in_game"

    asyncio.run(scenario())


def test_matchmaking_status_heartbeat_is_relayed_while_waiting_for_allocation(clean_active_game_index):
    async def scenario():
        import nats

        async with running_shard() as server:
            async with running_ws_gateway(shard_port=server.bound_port) as gw_port:
                async with websockets.connect(f"ws://localhost:{gw_port}") as client:
                    await client.send(encode_json_message(IdentifyMessage(username="gw_frank")))
                    # Same reasoning as test_identify_before_allocation_waits_for_game_allocated
                    # above - gives _handle_client time to register with
                    # _StatusRelay before this test publishes matchmaking.status.
                    await asyncio.sleep(0.2)

                    nats_connection = await nats.connect(NATS_URL)
                    status_payload = {"username": "gw_frank", "seconds_remaining": 42}
                    await nats_connection.publish("matchmaking.status", json.dumps(status_payload).encode("utf-8"))
                    await nats_connection.flush()

                    status_message = await recv_of_type(client, "matchmaking_status")
                    assert status_message == {"type": "matchmaking_status", "seconds_remaining": 42}

                    # Wait ends here (give-up, same as the timeout test below) -
                    # proves the heartbeat doesn't interfere with the terminal
                    # signal that follows it.
                    await nats_connection.publish(
                        "matchmaking.timeout", json.dumps({"username": "gw_frank"}).encode("utf-8")
                    )
                    await nats_connection.flush()
                    await nats_connection.close()

                    timeout_message = await recv_of_type(client, "matchmaking_timeout")
                    assert timeout_message == {"type": "matchmaking_timeout"}

    asyncio.run(scenario())


# Proves the whole spectator path end-to-end (gap 1 of Server_Design.md's
# own review): a room's game already exists (no allocation event of its own
# to wait on - see services/ws_gateway/main.py's own _resolve_shard
# docstring, case 2), and the spectator's IDENTIFY reaches this shard with
# no room.spectator_joined-style push ever having happened - decide_identify's
# own self-heal (server/router.py) is what's actually being proven, exactly
# the same way test_identify_for_an_already_allocated_username_relays_moves
# above proves decide_identify's seat-resend, not a lucky broadcast.
def test_identify_as_a_spectator_of_an_existing_room_relays_a_snapshot_with_no_seat(
    clean_active_game_index, clean_room_state
):
    async def scenario():
        rooms = RedisRoomRegistry(REDIS_URL)
        room = rooms.create("gw_room_creator")
        rooms.join(room.room_id, "gw_room_opponent")
        rooms.join(room.room_id, "gw_room_spectator")  # third joiner - a spectator, not the opponent

        async with running_shard() as server:
            RoomShardIndex(REDIS_URL).set(room.room_id, SHARD_ADDRESS)
            await server._loop._start_game(
                room.room_id, "gw_room_creator", "gw_room_opponent", room_id=room.room_id
            )

            async with running_ws_gateway(shard_port=server.bound_port) as gw_port:
                async with websockets.connect(f"ws://localhost:{gw_port}") as client:
                    await client.send(encode_json_message(IdentifyMessage(username="gw_room_spectator")))

                    ack = json.loads(await asyncio.wait_for(client.recv(), timeout=3.0))
                    assert ack == {"type": "identify_ack", "accepted": True}

                    # No "type" key at all on a raw snapshot payload (see
                    # protocol/snapshot_codec.py) - board_width is what
                    # decision.spectator_snapshot's own unit-test assertion
                    # already checks for the exact same shape (see
                    # tests/unit/test_router.py). Never a "seat" message -
                    # a spectator has no seat to be sent one for.
                    snapshot = json.loads(await asyncio.wait_for(client.recv(), timeout=3.0))
                    assert "board_width" in snapshot

                    # Checked *before* the client disconnects - decide_disconnect
                    # (server/router.py) discards a disconnecting spectator
                    # from spectator_usernames on its way out, same as any
                    # other spectator leaving; this is proving the self-heal
                    # actually happened, not asserting on state already
                    # unwound by that same disconnect handling.
                    assert "gw_room_spectator" in server._loop.get(room.room_id).spectator_usernames

    asyncio.run(scenario())


def test_identify_before_allocation_gives_up_on_matchmaking_timeout(clean_active_game_index):
    async def scenario():
        import nats

        async with running_shard() as server:
            async with running_ws_gateway(shard_port=server.bound_port) as gw_port:
                async with websockets.connect(f"ws://localhost:{gw_port}") as client:
                    await client.send(encode_json_message(IdentifyMessage(username="gw_erin")))
                    await asyncio.sleep(0.2)

                    nats_connection = await nats.connect(NATS_URL)
                    await nats_connection.publish(
                        "matchmaking.timeout", json.dumps({"username": "gw_erin"}).encode("utf-8")
                    )
                    await nats_connection.flush()
                    await nats_connection.close()

                    timeout_message = await recv_of_type(client, "matchmaking_timeout")
                    assert timeout_message == {"type": "matchmaking_timeout"}

    asyncio.run(scenario())
