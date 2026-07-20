"""End-to-end over a real socket: a real GameServer, a real
NetworkGameClient (the same transport play_online.py uses), no mocking.

NetworkGameClient's own blocking calls (login/play/wait_for_seat) must run
via run_in_executor rather than awaited directly - they're synchronous by
design (see server/network_client.py's own docstring: the GUI frame loop
that drives them isn't async), but calling one directly from this test's
own coroutine would block the very event loop the server task here needs
to keep running on, deadlocking the reply it's waiting for.
"""

import asyncio
import contextlib

import pytest

from boardio.board_parser import parse
from server.accounts import AccountStore
from server.network_client import MatchmakingTimeoutError, NetworkClientError, NetworkGameClient
from server.ws_server import GameServer

STARTING_BOARD = "wR . .\n. . .\n. . ."


@contextlib.asynccontextmanager
async def running_server(tick_interval_s: float = 0.01, board_text: str = STARTING_BOARD, **server_kwargs):
    account_store = AccountStore(":memory:")
    server = GameServer(
        lambda: parse(board_text), account_store, host="localhost", port=0, tick_interval_s=tick_interval_s, **server_kwargs
    )
    task = asyncio.create_task(server.run_forever())
    await server.wait_started()
    try:
        yield server
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        account_store.close()


async def _in_thread(func, *args):
    return await asyncio.get_event_loop().run_in_executor(None, func, *args)


def test_login_play_and_get_seated_over_a_real_connection():
    async def scenario():
        async with running_server() as server:
            client_a = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            client_b = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            try:
                login_a = await _in_thread(client_a.login, "alice", "secret123")
                login_b = await _in_thread(client_b.login, "bob", "hunter2")
                assert login_a == {"type": "login_ack", "accepted": True, "username": "alice", "rating": 1200}
                assert login_b["accepted"] is True

                play_a = await _in_thread(client_a.play)
                play_b = await _in_thread(client_b.play)
                assert play_a == {"type": "play_ack", "accepted": True, "reason": "queued"}
                assert play_b["accepted"] is True

                seat_a = await _in_thread(client_a.wait_for_seat)
                seat_b = await _in_thread(client_b.wait_for_seat)
                assert seat_a == {"type": "seat", "color": "white"}
                assert seat_b == {"type": "seat", "color": "black"}
            finally:
                client_a.close()
                client_b.close()

    asyncio.run(scenario())


def test_send_command_and_poll_messages_reflect_a_real_move():
    async def scenario():
        async with running_server() as server:
            client_a = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            client_b = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            try:
                await _in_thread(client_a.login, "alice", "secret123")
                await _in_thread(client_b.login, "bob", "hunter2")
                await _in_thread(client_a.play)
                await _in_thread(client_b.play)
                await _in_thread(client_a.wait_for_seat)  # white
                await _in_thread(client_b.wait_for_seat)  # black

                # Board is 3x3 with a lone white rook at (0, 0) - "a3" in
                # this board's own square-naming convention. Sliding it to
                # "c3" (0, 2) is legal for a rook.
                client_a.send_command("Wa3c3")

                deadline = asyncio.get_event_loop().time() + 5.0
                got_ack = False
                arrived = False
                while asyncio.get_event_loop().time() < deadline and not arrived:
                    await asyncio.sleep(0.05)
                    for message in await _in_thread(client_a.poll_messages):
                        if message.get("type") == "ack":
                            assert message == {"type": "ack", "accepted": True, "reason": "ok"}
                            got_ack = True
                        elif "pieces" in message:
                            if message["pieces"][0]["kind"] == "rook" and message["pieces"][0]["col"] == 2.0:
                                arrived = True

                assert got_ack
                assert arrived
            finally:
                client_a.close()
                client_b.close()

    asyncio.run(scenario())


def test_login_with_the_wrong_password_raises_instead_of_hanging():
    async def scenario():
        async with running_server() as server:
            account_store_client = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            try:
                # Register "alice" first so a second login attempt is a
                # *returning* username with the wrong password.
                await _in_thread(account_store_client.login, "alice", "secret123")
            finally:
                account_store_client.close()

            client = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            try:
                login_ack = await _in_thread(client.login, "alice", "wrong-password")
                assert login_ack == {"type": "login_ack", "accepted": False, "reason": "wrong_password"}
            finally:
                client.close()

    asyncio.run(scenario())


def test_wait_for_seat_times_out_when_no_match_ever_comes():
    async def scenario():
        async with running_server() as server:
            client = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            try:
                await _in_thread(client.login, "alice", "secret123")
                await _in_thread(client.play)

                with pytest.raises(NetworkClientError):
                    await _in_thread(client.wait_for_seat, 0.3)
            finally:
                client.close()

    asyncio.run(scenario())


def test_wait_for_seat_reacts_immediately_to_a_server_side_matchmaking_timeout():
    async def scenario():
        async with running_server(matchmaking_timeout_ms=100) as server:
            client = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            try:
                await _in_thread(client.login, "alice", "secret123")
                await _in_thread(client.play)

                start = asyncio.get_event_loop().time()
                # wait_for_seat's own default timeout (65s) is far longer
                # than the server's matchmaking_timeout_ms (100ms) above -
                # this only passes quickly if wait_for_seat reacts to the
                # server's own matchmaking_timeout message directly, rather
                # than silently discarding it and waiting out its own much
                # longer local deadline too.
                with pytest.raises(MatchmakingTimeoutError):
                    await _in_thread(client.wait_for_seat)
                elapsed = asyncio.get_event_loop().time() - start
                assert elapsed < 5.0
            finally:
                client.close()

    asyncio.run(scenario())


def test_create_room_join_room_and_get_seated_over_a_real_connection():
    async def scenario():
        async with running_server() as server:
            client_a = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            client_b = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            try:
                await _in_thread(client_a.login, "alice", "secret123")
                await _in_thread(client_b.login, "bob", "hunter2")

                created = await _in_thread(client_a.create_room)
                assert created["accepted"] is True
                room_id = created["room_id"]

                joined = await _in_thread(client_b.join_room, room_id)
                assert joined == {"type": "join_room_ack", "accepted": True, "room_id": room_id, "role": "opponent"}

                seat_a = await _in_thread(client_a.wait_for_seat)
                seat_b = await _in_thread(client_b.wait_for_seat)
                assert seat_a == {"type": "seat", "color": "white"}
                assert seat_b == {"type": "seat", "color": "black"}
            finally:
                client_a.close()
                client_b.close()

    asyncio.run(scenario())


def test_joining_a_room_that_already_has_an_opponent_makes_a_spectator():
    async def scenario():
        async with running_server() as server:
            client_a = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            client_b = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            client_c = await _in_thread(NetworkGameClient, "localhost", server.bound_port)
            try:
                await _in_thread(client_a.login, "alice", "secret123")
                await _in_thread(client_b.login, "bob", "hunter2")
                await _in_thread(client_c.login, "carol", "letmein")

                room_id = (await _in_thread(client_a.create_room))["room_id"]
                await _in_thread(client_b.join_room, room_id)
                await _in_thread(client_a.wait_for_seat)
                await _in_thread(client_b.wait_for_seat)

                joined = await _in_thread(client_c.join_room, room_id)
                assert joined == {"type": "join_room_ack", "accepted": True, "room_id": room_id, "role": "spectator"}

                # A spectator gets the board immediately, not just from the
                # next tick's broadcast - same call play_online.py's own
                # _wait_for_first_snapshot makes for a seated player.
                deadline = asyncio.get_event_loop().time() + 5.0
                saw_snapshot = False
                while asyncio.get_event_loop().time() < deadline and not saw_snapshot:
                    for message in await _in_thread(client_c.poll_messages):
                        if "pieces" in message:
                            saw_snapshot = True
                    if not saw_snapshot:
                        await asyncio.sleep(0.05)
                assert saw_snapshot
            finally:
                client_a.close()
                client_b.close()
                client_c.close()

    asyncio.run(scenario())
