"""End-to-end over a real socket: a real GameServer, real `websockets`
clients, no mocking of the transport or the game engine. port=0 lets the OS
pick a free port so this never collides with a real server already running
on the well-known port (see server/main.py).

matchmaking_timeout_ms/disconnect_grace_ms default here to a few hundred ms,
not the real 60s/20s production defaults (see server/matchmaking.py's
TIMEOUT_MS and server/session.py's DISCONNECT_GRACE_MS) - these tests
exercise the exact same code paths without actually waiting a minute or 20
seconds of wall-clock time per test.
"""

import asyncio
import contextlib
import json

import pytest
import websockets

from boardio.board_parser import parse
from server.accounts import AccountStore
from server.ws_server import GameServer

STARTING_BOARD = "wR . .\n. . .\n. . ."
KING_CAPTURE_BOARD = "wR bK"


# A connection's own reply to something it just sent (login_ack, play_ack,
# ack) and the tick loop's periodic broadcast/countdown are written by two
# independent tasks (see server/ws_server.py) - either can land first on
# the wire, so a real client can never assume "the next message is the one
# I'm waiting for." It has to read past any interleaved message instead.
async def recv_of_type(websocket, message_type: str, timeout: float = 2.0) -> dict:
    while True:
        message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=timeout))
        if message.get("type") == message_type:
            return message


async def login(websocket, username: str, password: str = "secret123") -> dict:
    await websocket.send(f"LOGIN {username} {password}")
    return await recv_of_type(websocket, "login_ack")


async def play(websocket) -> dict:
    await websocket.send("PLAY")
    return await recv_of_type(websocket, "play_ack")


@contextlib.asynccontextmanager
async def running_server(
    tick_interval_s: float = 0.01,
    board_text: str = STARTING_BOARD,
    account_store=None,
    matchmaking_timeout_ms: int = 300,
    disconnect_grace_ms: int = 300,
):
    # A fresh ":memory:" store per server unless a test supplies its own
    # (so it can inspect ratings afterward) - see server/accounts.py's own
    # db_path docstring for why there's no shared default to fall back on.
    owns_store = account_store is None
    if owns_store:
        account_store = AccountStore(":memory:")

    server = GameServer(
        lambda: parse(board_text),
        account_store,
        host="localhost",
        port=0,
        tick_interval_s=tick_interval_s,
        matchmaking_timeout_ms=matchmaking_timeout_ms,
        disconnect_grace_ms=disconnect_grace_ms,
    )
    task = asyncio.create_task(server.run_forever())
    await server.wait_started()
    try:
        yield server
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        if owns_store:
            account_store.close()


def test_login_alone_does_not_start_a_game():
    async def scenario():
        async with running_server() as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as ws:
                ack = await login(ws, "alice")
                assert ack == {"type": "login_ack", "accepted": True, "username": "alice", "rating": 1200}

                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.recv(), timeout=0.2)

    asyncio.run(scenario())


def test_play_before_login_is_rejected():
    async def scenario():
        async with running_server() as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as ws:
                await ws.send("PLAY")
                message = json.loads(await ws.recv())

                assert message == {"type": "error", "message": "login_required"}

    asyncio.run(scenario())


def test_two_compatible_players_get_matched_by_play():
    async def scenario():
        async with running_server() as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as a, websockets.connect(uri) as b:
                await login(a, "alice")
                await login(b, "bob")

                assert await play(a) == {"type": "play_ack", "accepted": True, "reason": "queued"}
                assert await play(b) == {"type": "play_ack", "accepted": True, "reason": "queued"}

                # alice queued first -> white; bob -> black.
                assert await recv_of_type(a, "seat") == {"type": "seat", "color": "white"}
                assert await recv_of_type(b, "seat") == {"type": "seat", "color": "black"}

    asyncio.run(scenario())


def test_incompatible_ratings_are_not_matched():
    async def scenario():
        account_store = AccountStore(":memory:")
        account_store.login("alice", "secret123")
        account_store.login("bob", "hunter2")
        account_store.update_rating("bob", 1200 + 101)  # just outside +-100

        # A huge matchmaking timeout - this test only checks "no match yet",
        # not "eventually times out" (see test_matchmaking_timeout_... below).
        async with running_server(account_store=account_store, matchmaking_timeout_ms=100_000) as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as a, websockets.connect(uri) as b:
                await login(a, "alice", "secret123")
                await login(b, "bob", "hunter2")
                await play(a)
                await play(b)

                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(a.recv(), timeout=0.3)

        account_store.close()

    asyncio.run(scenario())


def test_matchmaking_timeout_reports_cant_find_and_allows_replay():
    async def scenario():
        async with running_server(matchmaking_timeout_ms=100) as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as ws:
                await login(ws, "alice")
                await play(ws)

                timeout_message = await recv_of_type(ws, "matchmaking_timeout", timeout=3.0)
                assert timeout_message == {"type": "matchmaking_timeout"}

                # Removed from the queue - a fresh PLAY must queue again,
                # not be rejected as "already_queued".
                retry_ack = await play(ws)
                assert retry_ack == {"type": "play_ack", "accepted": True, "reason": "queued"}

    asyncio.run(scenario())


def test_already_queued_play_is_rejected():
    async def scenario():
        async with running_server(matchmaking_timeout_ms=100_000) as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as ws:
                await login(ws, "alice")
                await play(ws)

                ack = await play(ws)

                assert ack == {"type": "play_ack", "accepted": False, "reason": "already_queued"}

    asyncio.run(scenario())


def test_already_in_game_play_is_rejected():
    async def scenario():
        async with running_server() as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as a, websockets.connect(uri) as b:
                await login(a, "alice")
                await login(b, "bob")
                await play(a)
                await play(b)
                await recv_of_type(a, "seat")
                await recv_of_type(b, "seat")

                ack = await play(a)

                assert ack == {"type": "play_ack", "accepted": False, "reason": "already_in_game"}

    asyncio.run(scenario())


def test_move_command_when_not_in_any_game_is_rejected():
    async def scenario():
        async with running_server() as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as ws:
                await login(ws, "alice")
                # Logged in, but never played - no current_game to belong to.
                await ws.send("Wa3c3")
                ack = await recv_of_type(ws, "ack")

                assert ack == {"type": "ack", "accepted": False, "reason": "not_in_game"}

    asyncio.run(scenario())


def test_move_after_match_gets_an_ack_and_the_next_broadcast_reflects_it():
    async def scenario():
        async with running_server() as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as a, websockets.connect(uri) as b:
                await login(a, "alice")
                await login(b, "bob")
                await play(a)
                await play(b)
                seat_a = (await recv_of_type(a, "seat"))["color"]
                seat_b = (await recv_of_type(b, "seat"))["color"]
                assert seat_a == "white"
                assert seat_b == "black"

                # Board is 3x3 with a lone white rook at (0, 0) - "a3" in
                # this board's own square-naming convention (row 0 is rank
                # board_height, see boardio.algebraic_notation.square_name).
                # Sliding it 2 squares to "c3" (0, 2) is legal for a rook,
                # unlike a king (see rules/piece_rules.py's KingRule).
                await a.send("Wa3c3")
                ack = await recv_of_type(a, "ack")
                assert ack == {"type": "ack", "accepted": True, "reason": "ok"}

                # Keep draining broadcasts as they arrive, rather than
                # sleeping first and draining after - sleeping without
                # calling recv() lets broadcasts pile up in the socket
                # buffer, and a fixed-size drain loop would only ever see
                # the oldest, still-mid-flight ones.
                deadline = asyncio.get_event_loop().time() + 5.0
                arrived = False
                while asyncio.get_event_loop().time() < deadline:
                    payload = json.loads(await asyncio.wait_for(a.recv(), timeout=1))
                    if "pieces" not in payload:  # not a broadcast snapshot
                        continue
                    if payload["pieces"][0]["kind"] == "rook" and payload["pieces"][0]["col"] == 2.0:
                        arrived = True
                        break
                assert arrived

    asyncio.run(scenario())


def test_broadcast_carries_the_moves_log_and_score_panel_data():
    async def scenario():
        async with running_server(board_text=KING_CAPTURE_BOARD) as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as a, websockets.connect(uri) as b:
                await login(a, "alice")
                await login(b, "bob")
                await play(a)
                await play(b)
                await recv_of_type(a, "seat")  # alice = white
                await recv_of_type(b, "seat")  # bob = black

                await a.send("Wa1b1")
                await recv_of_type(a, "ack")

                # Drains real broadcasts until one carries the just-logged
                # move - the game_over-ending capture on this board can beat
                # a later broadcast to the wire (see server/ws_server.py's
                # _advance_current_game, which skips the panel broadcast
                # entirely once finalize_ratings_if_game_over fires), so
                # this only asserts the move-log entry showed up at all, not
                # a specific elapsed_ms or a mid-flight score value.
                deadline = asyncio.get_event_loop().time() + 5.0
                move_log_entry = None
                while asyncio.get_event_loop().time() < deadline:
                    payload = json.loads(await asyncio.wait_for(a.recv(), timeout=1))
                    if "pieces" not in payload:
                        continue
                    assert set(payload["score"]) == {"white", "black"}
                    if payload["move_log"]["white"]:
                        move_log_entry = payload["move_log"]["white"][0]
                        break

                assert move_log_entry is not None
                assert move_log_entry["notation"] == "Rxb1"
                assert isinstance(move_log_entry["elapsed_ms"], int)

    asyncio.run(scenario())


def test_wrong_seat_command_is_rejected_before_reaching_the_engine():
    async def scenario():
        async with running_server() as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as a, websockets.connect(uri) as b:
                await login(a, "alice")
                await login(b, "bob")
                await play(a)
                await play(b)
                await recv_of_type(a, "seat")  # alice = white
                await recv_of_type(b, "seat")  # bob = black

                # bob (black) tries to move using white's color letter.
                await b.send("Wa1a2")
                ack = await recv_of_type(b, "ack")

                assert ack == {"type": "ack", "accepted": False, "reason": "wrong_seat"}

    asyncio.run(scenario())


def test_game_over_broadcasts_ratings_and_frees_the_slot_for_a_new_match():
    async def scenario():
        account_store = AccountStore(":memory:")

        # A 1x2 board: white rook right next to black's king - one move
        # captures it and ends the game.
        async with running_server(board_text=KING_CAPTURE_BOARD, account_store=account_store) as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as a, websockets.connect(uri) as b:
                await login(a, "alice", "secret123")
                await login(b, "bob", "hunter2")
                await play(a)
                await play(b)
                assert (await recv_of_type(a, "seat"))["color"] == "white"
                assert (await recv_of_type(b, "seat"))["color"] == "black"

                await a.send("Wa1b1")
                ack = await recv_of_type(a, "ack")
                assert ack == {"type": "ack", "accepted": True, "reason": "ok"}

                game_over = await recv_of_type(a, "game_over", timeout=5.0)
                assert game_over == {"type": "game_over", "ratings": {"white": 1216, "black": 1184}}

                # The slot is free again - both can queue for a brand new
                # game, with a fresh board (see server/main.py's own
                # board_factory reasoning for why this can't just reuse
                # the finished one).
                await play(a)
                await play(b)
                new_seat_a = await recv_of_type(a, "seat", timeout=5.0)
                new_seat_b = await recv_of_type(b, "seat", timeout=5.0)
                assert new_seat_a == {"type": "seat", "color": "white"}
                assert new_seat_b == {"type": "seat", "color": "black"}

        account_store.close()

    asyncio.run(scenario())


def test_disconnect_starts_a_countdown_the_opponent_can_see():
    async def scenario():
        async with running_server(disconnect_grace_ms=300) as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as a:
                b = await websockets.connect(uri)
                await login(a, "alice")
                await login(b, "bob")
                await play(a)
                await play(b)
                assert (await recv_of_type(a, "seat"))["color"] == "white"
                await recv_of_type(b, "seat")

                await b.close()  # bob disconnects

                countdown = await recv_of_type(a, "disconnect_countdown", timeout=3.0)
                assert countdown["seat"] == "black"
                assert countdown["seconds_remaining"] >= 0

    asyncio.run(scenario())


def test_disconnected_player_can_reconnect_within_the_grace_window_and_resume():
    async def scenario():
        # A generous grace window relative to the 0.1s sleep below - under
        # a loaded test run (the full suite, not just this file), a small
        # margin here was observed to occasionally let real elapsed time
        # creep close enough to a tight window to flake.
        async with running_server(disconnect_grace_ms=10_000) as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as a:
                b = await websockets.connect(uri)
                await login(a, "alice")
                await login(b, "bob")
                await play(a)
                await play(b)
                await recv_of_type(a, "seat")  # alice = white
                await recv_of_type(b, "seat")  # bob = black

                await b.close()  # bob disconnects
                await asyncio.sleep(0.1)  # well within the 10s grace window

                async with websockets.connect(uri) as b2:
                    reconnect_ack = await login(b2, "bob")

                    assert reconnect_ack == {
                        "type": "login_ack",
                        "accepted": True,
                        "username": "bob",
                        "rating": 1200,
                        "reconnected": True,
                        "color": "black",
                    }

                    # The game actually continues - bob's connection is
                    # still recognized as part of it (a real move on this
                    # board fails for an unrelated reason - no black piece
                    # exists on STARTING_BOARD - but "not_in_game" is
                    # exactly what reconnection must have prevented).
                    await b2.send("Ba1a2")
                    ack = await recv_of_type(b2, "ack")
                    assert ack["reason"] != "not_in_game"

    asyncio.run(scenario())


def test_reconnecting_before_the_stale_socket_closes_does_not_evict_the_new_connection():
    async def scenario():
        async with running_server(disconnect_grace_ms=200) as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as a:
                b = await websockets.connect(uri)
                await login(a, "alice")
                await login(b, "bob")
                await play(a)
                await play(b)
                await recv_of_type(a, "seat")  # alice = white
                await recv_of_type(b, "seat")  # bob = black

                # bob's client reconnects (e.g. after a network blip) and
                # logs back in on a fresh socket *before* the server has
                # noticed the old one, b, is gone - b's recv loop is still
                # blocked, not yet closed.
                async with websockets.connect(uri) as b2:
                    await login(b2, "bob")

                    # The stale socket finally closes. Its _handle_connection
                    # finally-block must not tear down b2's now-current
                    # entry for "bob" just because the username matches.
                    await b.close()

                    # Comfortably past disconnect_grace_ms - a reintroduced
                    # bug would have force-resigned bob's seat by now.
                    await asyncio.sleep(0.5)

                    with pytest.raises(asyncio.TimeoutError):
                        await recv_of_type(a, "game_over", timeout=1.0)

                    # bob, via b2, is still recognized as the seated player -
                    # "not_in_game" is exactly what a wrongful eviction would
                    # produce.
                    await b2.send("Ba1a2")
                    ack = await recv_of_type(b2, "ack")
                    assert ack["reason"] != "not_in_game"

    asyncio.run(scenario())


def test_disconnect_without_reconnecting_in_time_forces_a_resignation():
    async def scenario():
        account_store = AccountStore(":memory:")

        async with running_server(account_store=account_store, disconnect_grace_ms=200) as server:
            uri = f"ws://localhost:{server.bound_port}"
            async with websockets.connect(uri) as a:
                b = await websockets.connect(uri)
                await login(a, "alice", "secret123")
                await login(b, "bob", "hunter2")
                await play(a)
                await play(b)
                assert (await recv_of_type(a, "seat"))["color"] == "white"
                assert (await recv_of_type(b, "seat"))["color"] == "black"

                await b.close()  # bob disconnects and never comes back

                game_over = await recv_of_type(a, "game_over", timeout=5.0)

                # bob (black) ran out the grace window - alice (white) wins.
                assert game_over == {"type": "game_over", "ratings": {"white": 1216, "black": 1184}}
                assert account_store.rating_for("bob") == 1184
                assert account_store.rating_for("alice") == 1216

        account_store.close()

    asyncio.run(scenario())
