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
from server.network_client import NetworkClientError, NetworkGameClient
from server.ws_server import GameServer

STARTING_BOARD = "wR . .\n. . .\n. . ."


@contextlib.asynccontextmanager
async def running_server(tick_interval_s: float = 0.01, board_text: str = STARTING_BOARD):
    account_store = AccountStore(":memory:")
    server = GameServer(lambda: parse(board_text), account_store, host="localhost", port=0, tick_interval_s=tick_interval_s)
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
