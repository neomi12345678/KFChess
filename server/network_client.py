"""Background-thread WebSocket transport for the networked GUI client
(play_online.py) - bridges the async server protocol (see
server/protocol.py, server/ws_server.py) to the synchronous, single-
threaded GUI frame loop view/canvas/window.py's GameWindow requires.

The asyncio event loop and the real websocket connection live entirely on
a dedicated background thread, for this object's whole lifetime - the GUI
thread only ever talks to it through send_command()/login()/play()/
wait_for_seat() (thread-safe, submitted onto that loop via
asyncio.run_coroutine_threadsafe) and poll_messages() (drains a plain
thread-safe queue.Queue the background thread's receive loop pushes into).
Nothing here does its own asyncio.run() from the calling thread - that
would require the GUI's own frame loop to be async, which
view/canvas/window.py's blocking cv2.waitKey() loop isn't.
"""

import asyncio
import json
import queue
import threading
import time
from typing import List, Optional

import websockets


class NetworkClientError(Exception):
    """Raised when connecting fails, or a blocking call (login/play/
    wait_for_seat) times out waiting for its expected reply."""


class NetworkGameClient:
    def __init__(self, host: str, port: int, connect_timeout: float = 5.0):
        self._incoming: "queue.Queue[dict]" = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._websocket = None
        self._connected = threading.Event()
        self._connect_error: Optional[BaseException] = None

        self._thread = threading.Thread(target=self._run, args=(host, port), daemon=True)
        self._thread.start()

        if not self._connected.wait(timeout=connect_timeout):
            raise NetworkClientError(f"timed out connecting to ws://{host}:{port}")
        if self._connect_error is not None:
            raise NetworkClientError(f"could not connect to ws://{host}:{port}") from self._connect_error

    # Runs entirely on the background thread - owns the event loop and the
    # real websocket connection for this client's whole lifetime.
    def _run(self, host: str, port: int) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_receive(host, port))
        finally:
            self._loop.close()

    async def _connect_and_receive(self, host: str, port: int) -> None:
        try:
            self._websocket = await websockets.connect(f"ws://{host}:{port}")
        except Exception as error:  # reported back to the constructor, never swallowed
            self._connect_error = error
            self._connected.set()
            return

        self._connected.set()
        try:
            async for message in self._websocket:
                self._incoming.put(json.loads(message))
        except websockets.exceptions.ConnectionClosed:
            pass

    # Thread-safe: called from the GUI thread, actually sends on the
    # background thread's own event loop.
    def send_command(self, text: str) -> None:
        asyncio.run_coroutine_threadsafe(self._websocket.send(text), self._loop)

    # Non-blocking - called once per GUI frame (see play_online.py) to
    # drain whatever arrived since the last poll, in order.
    def poll_messages(self) -> List[dict]:
        messages = []
        while True:
            try:
                messages.append(self._incoming.get_nowait())
            except queue.Empty:
                break
        return messages

    # The three blocking calls below are only ever used during the
    # terminal login/matchmaking handshake (see play_online.py), before
    # the GUI window opens and poll_messages() takes over - nothing else
    # is draining self._incoming concurrently at that point.
    def login(self, username: str, password: str, timeout: float = 10.0) -> dict:
        self.send_command(f"LOGIN {username} {password}")
        return self._wait_for_type("login_ack", timeout)

    def play(self, timeout: float = 10.0) -> dict:
        self.send_command("PLAY")
        return self._wait_for_type("play_ack", timeout)

    def wait_for_seat(self, timeout: float = 65.0) -> dict:
        return self._wait_for_type("seat", timeout)

    # Loops past any interleaved message of a different type rather than
    # raising on the first mismatch - mirrors server/client_cli.py's own
    # _recv_of_type, for the same reason: a reply to something just sent
    # and a periodic broadcast are written by independent tasks server-
    # side, so either can land first on the wire.
    def _wait_for_type(self, message_type: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NetworkClientError(f"timed out waiting for a '{message_type}' message")
            try:
                message = self._incoming.get(timeout=remaining)
            except queue.Empty:
                raise NetworkClientError(f"timed out waiting for a '{message_type}' message")
            if message.get("type") == message_type:
                return message

    def close(self) -> None:
        if self._websocket is not None and self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._websocket.close(), self._loop)
        self._thread.join(timeout=5.0)
