"""ConnectionRegistry.send's own docstring credits a plain, uncaught
ConnectionClosed/OSError with once crashing the entire server over one
player's dead socket - every other game along with it - so this is exercised
directly rather than only incidentally through a full running server (see
tests/integration/test_server_ws.py). discard_if_current's identity check
(a stale closing socket must never evict a newer reconnect already on file)
is the other race-condition-shaped behavior worth pinning down on its own.
"""

import asyncio

import pytest
import websockets.exceptions

from protocol.game_messages import ErrorMessage
from server.connections import ConnectionRegistry


class _FakeWebsocket:
    def __init__(self, raise_on_send=None):
        self.sent = []
        self._raise_on_send = raise_on_send

    async def send(self, text: str) -> None:
        if self._raise_on_send is not None:
            raise self._raise_on_send
        self.sent.append(text)


def test_send_delivers_a_dataclass_payload_as_its_registered_wire_dict():
    async def scenario():
        websocket = _FakeWebsocket()
        await ConnectionRegistry.send(websocket, ErrorMessage(message="boom"))
        assert websocket.sent == ['{"message": "boom", "type": "error"}']

    asyncio.run(scenario())


def test_send_delivers_a_plain_dict_payload_unchanged():
    async def scenario():
        websocket = _FakeWebsocket()
        await ConnectionRegistry.send(websocket, {"board_width": 3})
        assert websocket.sent == ['{"board_width": 3}']

    asyncio.run(scenario())


def test_send_swallows_connection_closed_instead_of_raising():
    async def scenario():
        websocket = _FakeWebsocket(raise_on_send=websockets.exceptions.ConnectionClosed(None, None))
        await ConnectionRegistry.send(websocket, ErrorMessage(message="boom"))  # must not raise

    asyncio.run(scenario())


def test_send_swallows_os_error_instead_of_raising():
    async def scenario():
        websocket = _FakeWebsocket(raise_on_send=OSError("socket already torn down"))
        await ConnectionRegistry.send(websocket, ErrorMessage(message="boom"))  # must not raise

    asyncio.run(scenario())


def test_send_lets_an_unrelated_exception_propagate():
    async def scenario():
        websocket = _FakeWebsocket(raise_on_send=ValueError("not a connection problem"))
        with pytest.raises(ValueError):
            await ConnectionRegistry.send(websocket, ErrorMessage(message="boom"))

    asyncio.run(scenario())


def test_send_to_username_is_a_no_op_when_nobody_is_registered():
    async def scenario():
        registry = ConnectionRegistry()
        await registry.send_to_username("nobody", ErrorMessage(message="boom"))  # must not raise

    asyncio.run(scenario())


def test_send_to_username_delivers_to_the_registered_socket():
    async def scenario():
        registry = ConnectionRegistry()
        websocket = _FakeWebsocket()
        registry.set("alice", websocket)

        await registry.send_to_username("alice", ErrorMessage(message="hi"))

        assert websocket.sent == ['{"message": "hi", "type": "error"}']

    asyncio.run(scenario())


def test_discard_if_current_clears_the_entry_when_the_socket_still_matches():
    registry = ConnectionRegistry()
    websocket = _FakeWebsocket()
    registry.set("alice", websocket)

    assert registry.discard_if_current("alice", websocket) is True
    assert registry.get("alice") is None


def test_discard_if_current_leaves_a_newer_reconnect_untouched():
    registry = ConnectionRegistry()
    stale_websocket = _FakeWebsocket()
    fresh_websocket = _FakeWebsocket()
    registry.set("alice", stale_websocket)
    registry.set("alice", fresh_websocket)  # a reconnect superseded the stale socket

    assert registry.discard_if_current("alice", stale_websocket) is False
    assert registry.get("alice") is fresh_websocket


def test_discard_if_current_is_false_for_a_username_with_no_entry_at_all():
    registry = ConnectionRegistry()
    assert registry.discard_if_current("nobody", _FakeWebsocket()) is False
