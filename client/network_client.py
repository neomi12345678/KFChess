"""Background-thread WebSocket transport for the networked GUI client
(play_online.py) - bridges the async server protocol (see
server/command_translation.py, server/ws_server.py) to the synchronous,
single-threaded GUI frame loop view/canvas/window.py's GameWindow requires.

The asyncio event loop and the real websocket connection live entirely on
a dedicated background thread, for this object's whole lifetime - the GUI
thread only ever talks to it through send_command()/login()/play()/
wait_for_seat() (thread-safe, submitted onto that loop via
asyncio.run_coroutine_threadsafe) and poll_messages() (drains a plain
thread-safe queue.Queue the background thread's receive loop pushes into).
Nothing here does its own asyncio.run() from the calling thread - that
would require the GUI's own frame loop to be async, which
view/canvas/window.py's blocking cv2.waitKey() loop isn't.

The receive loop decodes each incoming message exactly once, right here at
the network boundary - self._incoming (and thus poll_messages()) always
holds a typed item, never a raw dict a caller still has to decode itself:
one of protocol/lobby_messages.py's/protocol/game_messages.py's registered
dataclasses, or SnapshotBroadcast for the one payload that isn't one (see
its own docstring). client/network_message_adapter.py's NetworkMessageAdapter
and client/game_view_state.py's GameViewState both work off these typed
items directly, never a dict's own keys.
"""

import asyncio
import concurrent.futures
import json
import queue
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional, Type, TypeVar

import websockets

from client.client_config import CONNECT_TIMEOUT_S, INDEFINITE_WAIT_S
from protocol.game_messages import SeatMessage
from protocol.lobby_messages import (
    CreateRoomAckMessage,
    CreateRoomMessage,
    IdentifyAckMessage,
    IdentifyMessage,
    JoinRoomAckMessage,
    JoinRoomMessage,
    LoginAckMessage,
    LoginMessage,
    MatchmakingStatusMessage,
    MatchmakingTimeoutMessage,
    PlayAckMessage,
    PlayMessage,
)
from protocol.registry import encode_json_message, message_from_dict
from protocol.snapshot_codec import is_snapshot_payload

T = TypeVar("T")


# The one wire payload with no registered dataclass of its own - see
# protocol/snapshot_codec.py's own docstring on why the per-tick board+panel
# broadcast stays a plain dict rather than becoming one more registered
# message. Wrapping it here is what lets self._incoming hold a typed item
# uniformly, this one included, instead of its one exception forcing every
# consumer to keep handling a raw dict itself.
@dataclass(frozen=True)
class SnapshotBroadcast:
    payload: dict


class NetworkClientError(Exception):
    """Raised when connecting fails, or a blocking call (login/play/
    wait_for_seat) times out waiting for its expected reply."""


class MatchmakingTimeoutError(NetworkClientError):
    """Raised by wait_for_seat when the server itself reports
    matchmaking_timeout (see server/matchmaking.py's TIMEOUT_MS) - distinct
    from the base class's plain "nothing arrived in time" meaning, since
    here the server actively gave up on finding an opponent rather than us
    simply having stopped listening too soon."""




# json.loads(raw) always succeeds for anything the server actually sends,
# but never assumes the "type" tag is one this table recognizes - see
# message_from_dict's own None-on-unknown contract; a message this decodes
# to None (some future/foreign type this client doesn't know about yet)
# passes through as the raw dict, the same "unknown is harmlessly ignored"
# behavior every existing consumer already relies on, rather than raising
# and killing this background thread's receive loop over it.
#
# Public (not just this class's own receive loop) - client/client_cli.py's
# terminal client shares this exact decode step too, instead of keeping its
# own second, raw-dict-based interpretation of the same wire vocabulary (see
# its own docstring).
def decode_incoming(raw_text: str) -> object:
    payload = json.loads(raw_text)
    if is_snapshot_payload(payload):
        return SnapshotBroadcast(payload=payload)
    decoded = message_from_dict(payload)
    return decoded if decoded is not None else payload


class NetworkGameClient:
    # api_gateway_port unset (the default) keeps play() sending PlayMessage
    # over the websocket exactly as before - the same "opt-in, off by
    # default" convention every other piece of split-service infra in this
    # project follows (DATABASE_URL/REDIS_URL/NATS_URL/EXTERNAL_MATCHMAKER):
    # a bare-metal run (README's own `python -m server.main` + `python
    # play_online.py`, and every existing test building a real GameServer
    # with no API Gateway anywhere) has nothing at that port to answer.
    # Only a caller that knows a real services/api_gateway/main.py is actually
    # running (see play_online.py's own --api-gateway-port) should pass
    # this. api_gateway_host defaults to the same host the websocket
    # connects to (the common case: both services published on the same
    # machine/DNS name, just different ports - see docker-compose.yml).
    def __init__(
        self,
        host: str,
        port: int,
        connect_timeout: float = CONNECT_TIMEOUT_S,
        api_gateway_host: Optional[str] = None,
        api_gateway_port: Optional[int] = None,
        # None (the default) keeps today's plaintext ws://, http:// behavior
        # unchanged - see tls_config.py's own docstring. A real ssl.SSLContext
        # (tls_config.get_client_ssl_context) switches both the websocket
        # connection below and every api_gateway_port REST call in login()/
        # play() to wss://, https:// together - one flag for both, since a
        # real deployment always terminates TLS the same way on every public
        # listener a client talks to (see Server_Design.md §3's edge tier).
        ssl_context: Optional[ssl.SSLContext] = None,
    ):
        self._incoming: "queue.Queue[object]" = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Set by _run the instant the background thread starts - lets a
        # connect-timeout below cancel the still-pending connect attempt
        # instead of leaving it (and the thread blocked inside it) running
        # forever with no reference anything could ever cancel it through,
        # since this constructor is about to raise and never hand the
        # caller an object to call close() on.
        self._connect_task: Optional["asyncio.Task"] = None
        self._websocket = None
        self._connected = threading.Event()
        # Set once the background thread's receive loop exits for any reason
        # (server closed the socket, the network dropped, ...) - the GUI
        # frame loop (play_online.py) has no other way to learn the
        # connection is gone, since poll_messages() just silently starts
        # returning an empty list forever otherwise. See is_connected().
        self._connection_lost = threading.Event()
        self._connect_error: Optional[BaseException] = None
        self._username: Optional[str] = None
        # The session token login() captures from a successful LoginAckMessage
        # - attached to every later IdentifyMessage (a reconnect, or the
        # REST-login path's own connection-registration step below) and to
        # play()'s own REST body, proving this client is who it claims rather
        # than just asserting it (see server/accounts.py's
        # issue_session_token/verify_session_token).
        self._token: Optional[str] = None
        self._api_gateway_host = api_gateway_host if api_gateway_host is not None else host
        self._api_gateway_port = api_gateway_port
        self._ssl_context = ssl_context
        self._ws_scheme = "wss" if ssl_context is not None else "ws"
        self._http_scheme = "https" if ssl_context is not None else "http"

        self._thread = threading.Thread(target=self._run, args=(host, port), daemon=True)
        self._thread.start()

        if not self._connected.wait(timeout=connect_timeout):
            # Cancels the still-pending websockets.connect() (see _run) -
            # without this, a host that never completes or fails the
            # handshake (firewalled, silently dropping the TCP connection)
            # leaves the background thread blocked inside it indefinitely,
            # even though this constructor is about to raise and this
            # half-built client is never returned to anything that could
            # call close() on it later.
            if self._loop is not None and self._connect_task is not None:
                self._loop.call_soon_threadsafe(self._connect_task.cancel)
            raise NetworkClientError(f"timed out connecting to {self._ws_scheme}://{host}:{port}")
        if self._connect_error is not None:
            raise NetworkClientError(f"could not connect to {self._ws_scheme}://{host}:{port}") from self._connect_error

    # Runs entirely on the background thread - owns the event loop and the
    # real websocket connection for this client's whole lifetime. Runs
    # _connect_and_receive as an explicit Task (not just
    # run_until_complete(coroutine)) so __init__'s own connect-timeout
    # branch has something to actually cancel - a bare coroutine handed to
    # run_until_complete has no handle another thread could reach in to
    # stop early.
    def _run(self, host: str, port: int) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._connect_task = self._loop.create_task(self._connect_and_receive(host, port))
        try:
            self._loop.run_until_complete(self._connect_task)
        except asyncio.CancelledError:
            pass
        finally:
            self._loop.close()

    async def _connect_and_receive(self, host: str, port: int) -> None:
        try:
            self._websocket = await websockets.connect(f"{self._ws_scheme}://{host}:{port}", ssl=self._ssl_context)
        except Exception as error:  # reported back to the constructor, never swallowed
            self._connect_error = error
            self._connected.set()
            return

        self._connected.set()
        try:
            async for message in self._websocket:
                # One malformed/unrecognized-shape message (a recognized
                # "type" tag with a missing/mistyped field, or plain garbage
                # that isn't even valid JSON) must not take the whole
                # receive loop down with it - that would silently orphan
                # this connection exactly like a real disconnect, just from
                # a cause the server-side fix for the same class of bug
                # (see server/ws_server.py's _handle_message) doesn't cover.
                try:
                    self._incoming.put(decode_incoming(message))
                except Exception as error:
                    print(f"NetworkGameClient: ignoring malformed message: {error}")
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as error:
            # Anything else the transport can raise (a reset socket, a TLS
            # error mid-stream, ...) ends the receive loop the same way a
            # clean disconnect does - logged here instead of propagating
            # out of _run and becoming an unhandled-exception-in-a-thread
            # warning nobody is watching for.
            print(f"NetworkGameClient: receive loop ending after a transport error: {error}")
        finally:
            # However this loop ended - a clean ConnectionClosed, or the
            # socket dying some other way - the websocket is no longer
            # usable. Clearing it (rather than leaving a dead reference
            # behind) is what makes close()'s own guard below correct.
            self._websocket = None
            self._connection_lost.set()

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

    # True until the background thread's receive loop has ended for any
    # reason. A caller polling this every frame (see play_online.py) is the
    # only way to learn the connection died - poll_messages() alone can't
    # tell "nothing new arrived this frame" apart from "nothing will ever
    # arrive again", since both drain to an empty list.
    def is_connected(self) -> bool:
        return not self._connection_lost.is_set()

    # Non-blocking - called once per GUI frame (see play_online.py) to
    # drain whatever arrived since the last poll, in order. Each item is
    # already a typed value (a registered protocol dataclass, or
    # SnapshotBroadcast) - see decode_incoming.
    def poll_messages(self) -> List[object]:
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
    # api_gateway_port unset (the default - see __init__'s own docstring):
    # LoginMessage over the websocket, exactly as before. Set: an HTTP POST
    # to the standalone API Gateway instead (see services/api_gateway/main.py's
    # POST /login) - authentication only, so once accepted this still sends
    # an IdentifyMessage over the websocket and waits for its ack, the same
    # connection-registration step _handle_login itself performs on the
    # all-websocket path (see server/ws_server.py's _handle_identify). Either
    # way, the returned LoginAckMessage carries the same reconnected/color
    # fields - server/interfaces.py's ActiveGameIndexProtocol is what lets
    # POST /login answer those without reaching into any GameLoop directly
    # (see its own docstring for the one branch - a room surviving a server
    # restart - this REST path doesn't replicate).
    def login(self, username: str, password: str, timeout: float = 10.0) -> LoginAckMessage:
        if self._api_gateway_port is None:
            self.send_command(encode_json_message(LoginMessage(username=username, password=password)))
            ack = self._wait_for_type(LoginAckMessage, timeout)
            if ack.accepted:
                # Needed by play() below - PLAY is no longer a wire message
                # this class sends over the websocket (see its own docstring),
                # so the username has to be remembered here instead of being
                # implicit in "whichever connection sent it."
                self._username = ack.username
                self._token = ack.token
            return ack

        url = f"{self._http_scheme}://{self._api_gateway_host}:{self._api_gateway_port}/login"
        request = urllib.request.Request(
            url,
            data=json.dumps({"username": username, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=self._ssl_context) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError) as error:
            raise NetworkClientError(f"could not reach the API Gateway for /login: {error}") from error

        ack = LoginAckMessage(
            accepted=body["accepted"],
            reason=body.get("reason"),
            username=body.get("username"),
            rating=body.get("rating"),
            reconnected=body.get("reconnected"),
            color=body.get("color"),
            token=body.get("token"),
        )
        if ack.accepted:
            self._username = ack.username
            self._token = ack.token
            self.send_command(encode_json_message(IdentifyMessage(username=ack.username, token=ack.token)))
            self._wait_for_type(IdentifyAckMessage, timeout)
        return ack

    # api_gateway_port unset (the default - see __init__'s own docstring):
    # PlayMessage over the websocket, exactly as before - server/router.py's
    # CommandRouter still has this PLAY branch (see server/ws_server.py),
    # kept specifically so this default path (and every test building a
    # plain GameServer with no API Gateway) keeps working unchanged. Set:
    # an HTTP POST to the standalone API Gateway instead (see
    # services/api_gateway/main.py). Either way, wait_for_seat below is unchanged:
    # SeatMessage/MatchmakingStatusMessage/MatchmakingTimeoutMessage still
    # arrive over this same websocket connection, since the API Gateway
    # itself holds no websocket to send anything on - only the enqueue
    # step ever moves, not the notifications.
    def play(self, timeout: float = 10.0) -> PlayAckMessage:
        if self._api_gateway_port is None:
            self.send_command(encode_json_message(PlayMessage()))
            return self._wait_for_type(PlayAckMessage, timeout)

        url = f"{self._http_scheme}://{self._api_gateway_host}:{self._api_gateway_port}/play"
        request = urllib.request.Request(
            url,
            data=json.dumps({"username": self._username, "token": self._token}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=self._ssl_context) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError) as error:
            raise NetworkClientError(f"could not reach the API Gateway for /play: {error}") from error
        return PlayAckMessage(accepted=body["accepted"], reason=body["reason"])

    # timeout is a defensive upper bound, not the expected path - the server
    # gives up and reports matchmaking_timeout on its own after
    # server/matchmaking.py's TIMEOUT_MS (60s by default), which
    # _wait_for_type's stop_types below reacts to immediately rather than
    # this call silently discarding it and waiting out its own timeout too.
    # on_status, if given, is called for each periodic MatchmakingStatusMessage
    # seen while waiting (see server/matchmaking.py's own
    # MATCHMAKING_STATUS_INTERVAL_MS) instead of silently discarding it like
    # any other non-matching message - callers not currently queued for a PLAY
    # match (create_room/join_room's own wait_for_seat calls, waiting on a room
    # opponent instead) simply never see one regardless, so they can omit it.
    def wait_for_seat(
        self, timeout: float = 65.0, on_status: Optional[Callable[[MatchmakingStatusMessage], None]] = None
    ) -> SeatMessage:
        return self._wait_for_type(
            SeatMessage,
            timeout,
            stop_types={MatchmakingTimeoutMessage: MatchmakingTimeoutError},
            on_status=on_status,
        )

    # The section-6 room flow (see server/rooms.py) - create_room's own
    # reply carries the room id (nothing to wait_for_seat for yet, since a
    # freshly created room has no opponent); join_room's carries "role"
    # instead (opponent vs spectator, see play_online.py's own handling of
    # each), decided by the server, not requested by the caller.
    def create_room(self, timeout: float = 10.0) -> CreateRoomAckMessage:
        self.send_command(encode_json_message(CreateRoomMessage()))
        return self._wait_for_type(CreateRoomAckMessage, timeout)

    def join_room(self, room_id: str, timeout: float = 10.0) -> JoinRoomAckMessage:
        self.send_command(encode_json_message(JoinRoomMessage(room_id=room_id)))
        return self._wait_for_type(JoinRoomAckMessage, timeout)

    # Loops past any interleaved message of a different type rather than
    # raising on the first mismatch - mirrors client/client_cli.py's own
    # _recv_of_type, for the same reason: a reply to something just sent
    # and a periodic broadcast are written by independent tasks server-
    # side, so either can land first on the wire. stop_types names message
    # types that should abort the wait immediately with a specific error
    # instead of being silently discarded like any other non-matching
    # message - wait_for_seat's own matchmaking_timeout being the only
    # current use (see above). on_status is a narrower hook for a message
    # that should neither end the wait nor raise - just be observed (see
    # wait_for_seat's own MatchmakingStatusMessage use) - and is checked
    # before stop_types so a status message is never mistaken for one.
    def _wait_for_type(
        self,
        message_type: Type[T],
        timeout: float,
        stop_types: Optional[dict] = None,
        on_status: Optional[Callable[[MatchmakingStatusMessage], None]] = None,
    ) -> T:
        stop_types = stop_types or {}
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NetworkClientError(f"timed out waiting for a '{message_type.__name__}' message")
            try:
                message = self._incoming.get(timeout=remaining)
            except queue.Empty:
                raise NetworkClientError(f"timed out waiting for a '{message_type.__name__}' message")
            if isinstance(message, message_type):
                return message
            if on_status is not None and isinstance(message, MatchmakingStatusMessage):
                on_status(message)
                continue
            stop_error = stop_types.get(type(message))
            if stop_error is not None:
                raise stop_error(
                    f"server reported {type(message).__name__} while waiting for a '{message_type.__name__}' message"
                )

    def close(self) -> None:
        # self._websocket/_loop being non-None is necessary but not
        # sufficient - the receive loop may have already ended (server
        # disconnect, a transport error) and closed the loop out from under
        # us between that check and this call. run_coroutine_threadsafe
        # raises RuntimeError synchronously in that case; there is nothing
        # left to close, so that's a no-op here, not a crash for the caller.
        if self._websocket is not None and self._loop is not None and not self._loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(self._websocket.close(), self._loop)
            except RuntimeError:
                pass
        self._thread.join(timeout=5.0)
