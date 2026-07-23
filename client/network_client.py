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
import concurrent.futures
import json
import queue
import threading
import time
from typing import List, Optional

import websockets

from protocol.lobby_messages import build_create_room, build_join_room, build_login, build_play
from protocol.types import CREATE_ROOM_ACK, JOIN_ROOM_ACK, LOGIN_ACK, MATCHMAKING_TIMEOUT, PLAY_ACK, SEAT


class NetworkClientError(Exception):
    """Raised when connecting fails, or a blocking call (login/play/
    wait_for_seat) times out waiting for its expected reply."""


class MatchmakingTimeoutError(NetworkClientError):
    """Raised by wait_for_seat when the server itself reports
    matchmaking_timeout (see server/matchmaking.py's TIMEOUT_MS) - distinct
    from the base class's plain "nothing arrived in time" meaning, since
    here the server actively gave up on finding an opponent rather than us
    simply having stopped listening too soon."""


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
    # background thread's own event loop. Fire-and-forget by design (the GUI
    # frame loop can't block on a per-frame send) - but a send that raises
    # (e.g. the socket died between frames) must not vanish without a trace,
    # so the returned Future's outcome is still checked, just asynchronously
    # via this callback rather than by blocking on it here.
    def send_command(self, text: str) -> None:
        future = asyncio.run_coroutine_threadsafe(self._websocket.send(text), self._loop)
        future.add_done_callback(self._report_send_failure)

    @staticmethod
    def _report_send_failure(future: concurrent.futures.Future) -> None:
        error = future.exception()
        if error is not None:
            print(f"NetworkGameClient: failed to send command: {error}")

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
        self.send_command(build_login(username, password))
        return self._wait_for_type(LOGIN_ACK, timeout)

    def play(self, timeout: float = 10.0) -> dict:
        self.send_command(build_play())
        return self._wait_for_type(PLAY_ACK, timeout)

    # timeout is a defensive upper bound, not the expected path - the server
    # gives up and reports matchmaking_timeout on its own after
    # server/matchmaking.py's TIMEOUT_MS (60s by default), which
    # _wait_for_type's stop_types below reacts to immediately rather than
    # this call silently discarding it and waiting out its own timeout too.
    def wait_for_seat(self, timeout: float = 65.0) -> dict:
        return self._wait_for_type(SEAT, timeout, stop_types={MATCHMAKING_TIMEOUT: MatchmakingTimeoutError})

    # The section-6 room flow (see server/rooms.py) - create_room's own
    # reply carries the room id (nothing to wait_for_seat for yet, since a
    # freshly created room has no opponent); join_room's carries "role"
    # instead (opponent vs spectator, see play_online.py's own handling of
    # each), decided by the server, not requested by the caller.
    def create_room(self, timeout: float = 10.0) -> dict:
        self.send_command(build_create_room())
        return self._wait_for_type(CREATE_ROOM_ACK, timeout)

    def join_room(self, room_id: str, timeout: float = 10.0) -> dict:
        self.send_command(build_join_room(room_id))
        return self._wait_for_type(JOIN_ROOM_ACK, timeout)

    # Loops past any interleaved message of a different type rather than
    # raising on the first mismatch - mirrors client/client_cli.py's own
    # _recv_of_type, for the same reason: a reply to something just sent
    # and a periodic broadcast are written by independent tasks server-
    # side, so either can land first on the wire. stop_types names message
    # types that should abort the wait immediately with a specific error
    # instead of being silently discarded like any other non-matching
    # message - wait_for_seat's own matchmaking_timeout being the only
    # current use (see above).
    def _wait_for_type(self, message_type: str, timeout: float, stop_types: Optional[dict] = None) -> dict:
        stop_types = stop_types or {}
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
            stop_error = stop_types.get(message.get("type"))
            if stop_error is not None:
                raise stop_error(f"server reported '{message['type']}' while waiting for a '{message_type}' message")

    def close(self) -> None:
        if self._websocket is not None and self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._websocket.close(), self._loop)
        self._thread.join(timeout=5.0)
