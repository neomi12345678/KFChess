"""Minimal shell client for the KFChess server: prompts for a username and
password in the terminal (the Home screen's own "do it in a shell, not via
GUI" login step - see server/ws_server.py's LOGIN handling, checked against
server/accounts.py's SQLite-backed accounts), then either type "play" to
enter ELO matchmaking or "create room"/"join room <id>"/"cancel room" for
the section-6 room flow (see server/rooms.py) - moves by hand once seated.
A stand-in until the real GUI talks to the server directly, not a
replacement for it.

Incoming wire messages are decoded through the exact same
client/network_client.py's decode_incoming this project's real GUI client
uses, not a second, raw-dict-based interpretation of the same vocabulary -
_ClientState.observe below pattern-matches on the typed result (a registered
protocol dataclass, or SnapshotBroadcast for the one payload that isn't one)
the same way client/game_view_state.py's GameViewState does.

Run: python -m client.client_cli [--host HOST] [--port PORT]
"""

import argparse
import asyncio
import getpass
import json
import urllib.error
import urllib.request
from typing import Optional, Type, Union

import websockets

from boardio.algebraic_notation import parse_square
from client.client_config import CANCEL_ROOM_INPUT, CREATE_ROOM_INPUT, JOIN_ROOM_PREFIX, PLAY_INPUT
from client.network_client import SnapshotBroadcast, decode_incoming
from protocol.game_messages import GameOverMessage, JumpMessage, MoveMessage, SeatMessage, build_jump, build_move
from protocol.lobby_messages import (
    CancelRoomMessage,
    CreateRoomMessage,
    IdentifyAckMessage,
    IdentifyMessage,
    JoinRoomMessage,
    LoginAckMessage,
    LoginMessage,
    PlayMessage,
)
from protocol.registry import encode_json_message
from protocol.types import API_GATEWAY_PORT, HOST, PORT


class InputError(Exception):
    """Raised when a typed line doesn't match any input shape below."""


# The seat this connection is currently playing, if any - unknown until a
# SeatMessage arrives (see observe below), since matchmaking (not login) is
# what assigns one now. board_height is similarly unknown until the first
# snapshot broadcast (the only wire message that carries it) - both are what
# build_command needs to turn typed algebraic input into a real Position,
# now that the wire format itself carries one directly rather than algebraic
# text (see protocol/game_messages.py's own docstring). A plain mutable
# holder so _print_incoming (which sees these messages) and _read_commands
# (which needs them to build a move) can share the state that changes after
# login.
class _ClientState:
    def __init__(self, seat: Optional[str] = None, board_height: Optional[int] = None):
        self.seat = seat
        self.board_height = board_height

    # message is whatever decode_incoming already decoded it to - a
    # registered protocol dataclass, SnapshotBroadcast, or (for a "type" this
    # client doesn't recognize) the raw dict itself. Anything this
    # isinstance chain doesn't match is silently ignored, the same "unknown
    # is a no-op" contract every other consumer of decode_incoming's output
    # already has.
    def observe(self, message: object) -> None:
        if isinstance(message, SeatMessage):
            self.seat = message.color
        elif isinstance(message, GameOverMessage):
            self.seat = None
        elif isinstance(message, SnapshotBroadcast):
            self.board_height = message.payload["board_height"]


# Typed shorthand -> a real MoveMessage/JumpMessage (see
# server/command_translation.py's command_from_message, and
# boardio.algebraic_notation.parse_square for the
# text->Position half of this). The connection's own color is implicit
# (whichever seat matchmaking assigned), so a player never has to type
# "W"/"B" themselves:
#   "e2e4"     -> move
#   "jump e4"  -> jump
def build_command(raw_input: str, seat: str, board_height: int) -> Union[MoveMessage, JumpMessage]:
    text = raw_input.strip()
    if not text:
        raise InputError("empty input")

    parts = text.split(None, 1)

    if parts[0].lower() == "jump":
        if len(parts) < 2 or not parts[1].strip():
            raise InputError("jump requires a square, e.g. 'jump e4'")
        return build_jump(seat, _parse_typed_square(parts[1].strip(), board_height))

    # A move's source/dest are both fixed-width squares (one file letter,
    # then digits) with no separator, so the split point is wherever the
    # rank digits of the first square end and the second square's file
    # letter begins.
    split = 1
    while split < len(text) and text[split].isdigit():
        split += 1
    if split >= len(text):
        raise InputError(f"malformed move: '{text}'")

    source = _parse_typed_square(text[:split], board_height)
    destination = _parse_typed_square(text[split:], board_height)
    return build_move(seat, source, destination)


def _parse_typed_square(square: str, board_height: int):
    try:
        return parse_square(square, board_height)
    except ValueError as error:
        raise InputError(str(error)) from error


# A connection's own reply to something it just sent (login_ack, play_ack,
# ack) and the tick loop's periodic broadcast/countdown are written by two
# independent tasks on the server (see server/ws_server.py) - either can
# land first, so this reads past any interleaved broadcast instead of
# assuming the very next message is the one being waited for.
async def _recv_of_type(websocket, message_class: Type) -> object:
    while True:
        decoded = decode_incoming(await websocket.recv())
        if isinstance(decoded, message_class):
            return decoded


async def _print_incoming(websocket, state: _ClientState) -> None:
    async for message in websocket:
        decoded = decode_incoming(message)
        state.observe(decoded)
        if not isinstance(decoded, SnapshotBroadcast):  # a broadcast snapshot has nothing worth printing here
            print(decoded)


# api_gateway_port unset (the default - see _parse_args's own --api-gateway-port
# help text): a plain websocket PlayMessage send, exactly as before -
# server/router.py's CommandRouter still has this PLAY branch (see
# server/ws_server.py), kept specifically so this default path (and every
# test building a plain GameServer with no API Gateway) keeps working
# unchanged. Set: an HTTP POST to the standalone API Gateway instead (see
# services/api_gateway/main.py) - a plain blocking call, same as this module's own
# build_command/input() calls, run via run_in_executor so it doesn't block
# this coroutine's event loop.
def _post_play(username: str, api_gateway_host: str, api_gateway_port: int) -> dict:
    url = f"http://{api_gateway_host}:{api_gateway_port}/play"
    request = urllib.request.Request(
        url,
        data=json.dumps({"username": username}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10.0) as response:
        return json.loads(response.read())


# Same pattern as _post_play above, for services/api_gateway/main.py's own
# POST /login (see that module's docstring for the one branch of
# LoginMessage's decide_login this narrower endpoint doesn't replicate).
def _post_login(username: str, password: str, api_gateway_host: str, api_gateway_port: int) -> dict:
    url = f"http://{api_gateway_host}:{api_gateway_port}/login"
    request = urllib.request.Request(
        url,
        data=json.dumps({"username": username, "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10.0) as response:
        return json.loads(response.read())


async def _read_commands(
    websocket, state: _ClientState, username: str, api_gateway_host: str, api_gateway_port: Optional[int]
) -> None:
    loop = asyncio.get_event_loop()
    while True:
        raw = await loop.run_in_executor(None, input, "> ")
        text = raw.strip()
        lowered = text.lower()

        if lowered == PLAY_INPUT:
            if api_gateway_port is None:
                await websocket.send(encode_json_message(PlayMessage()))
                continue
            try:
                body = await loop.run_in_executor(None, _post_play, username, api_gateway_host, api_gateway_port)
            except urllib.error.URLError as error:
                print(f"(could not reach the API Gateway: {error})")
                continue
            print(f"play_ack: {body}")
            continue

        if lowered == CREATE_ROOM_INPUT:
            await websocket.send(encode_json_message(CreateRoomMessage()))
            continue

        if lowered == CANCEL_ROOM_INPUT:
            await websocket.send(encode_json_message(CancelRoomMessage()))
            continue

        if lowered.startswith(JOIN_ROOM_PREFIX):
            room_id = text[len(JOIN_ROOM_PREFIX):].strip()
            if not room_id:
                print("(usage: 'join room <id>')")
                continue
            await websocket.send(encode_json_message(JoinRoomMessage(room_id=room_id)))
            continue

        if state.seat is None or state.board_height is None:
            print("(not seated yet - type 'play', 'create room', or 'join room <id>')")
            continue

        try:
            command = build_command(text, state.seat, state.board_height)
        except InputError as error:
            print(f"(ignored: {error})")
            continue
        await websocket.send(encode_json_message(command))


def _parse_args() -> argparse.Namespace:  # pragma: no cover
    parser = argparse.ArgumentParser(description="KFChess terminal client")
    parser.add_argument("--host", default=HOST, help=f"server host (default: {HOST})")
    parser.add_argument("--port", type=int, default=PORT, help=f"server port (default: {PORT})")
    # Both unset by default: PLAY over the websocket, same as always (see
    # _read_commands's own handling) - a bare-metal `python -m server.main`
    # has no API Gateway anywhere to answer. Pass --api-gateway-port only
    # when actually running the full split-service docker-compose.yml
    # stack; --api-gateway-host then defaults to --host (both services
    # published on the same machine/DNS name, just different ports).
    parser.add_argument("--api-gateway-host", default=None, help="API Gateway host (default: same as --host)")
    parser.add_argument(
        "--api-gateway-port",
        type=int,
        default=None,
        help=f"API Gateway port (unset: PLAY over the websocket; typically {API_GATEWAY_PORT})",
    )
    return parser.parse_args()


async def _main(host: str, port: int, api_gateway_host: str, api_gateway_port: Optional[int]) -> None:  # pragma: no cover
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")

    uri = f"ws://{host}:{port}"
    async with websockets.connect(uri) as websocket:
        # api_gateway_port unset (the default): LoginMessage over the
        # websocket, exactly as before. Set: an HTTP POST to the standalone
        # API Gateway instead (see _post_login above) - authentication only,
        # so once accepted this still sends an IdentifyMessage over the
        # websocket and waits for its ack, the same connection-registration
        # step _handle_login itself performs on the all-websocket path (see
        # server/ws_server.py's _handle_identify).
        if api_gateway_port is None:
            await websocket.send(encode_json_message(LoginMessage(username=username, password=password)))
            login_ack = await _recv_of_type(websocket, LoginAckMessage)
        else:
            loop = asyncio.get_event_loop()
            try:
                body = await loop.run_in_executor(
                    None, _post_login, username, password, api_gateway_host, api_gateway_port
                )
            except urllib.error.URLError as error:
                print(f"(could not reach the API Gateway: {error})")
                return
            login_ack = LoginAckMessage(
                accepted=body["accepted"],
                reason=body.get("reason"),
                username=body.get("username"),
                rating=body.get("rating"),
                reconnected=body.get("reconnected"),
                color=body.get("color"),
            )
            if login_ack.accepted:
                await websocket.send(encode_json_message(IdentifyMessage(username=login_ack.username)))
                await _recv_of_type(websocket, IdentifyAckMessage)

        if not login_ack.accepted:
            print(f"Login failed: {login_ack.reason}")
            return
        print(f"Logged in as {login_ack.username} (rating {login_ack.rating})")

        if login_ack.reconnected:
            state = _ClientState(seat=login_ack.color)
            print(f"Reconnected to your game as {state.seat}")
        else:
            state = _ClientState()
            print("Type 'play' to find a match.")

        await asyncio.gather(
            _print_incoming(websocket, state),
            _read_commands(websocket, state, username, api_gateway_host, api_gateway_port),
        )


def main() -> None:  # pragma: no cover
    args = _parse_args()
    api_gateway_host = args.api_gateway_host if args.api_gateway_host is not None else args.host
    asyncio.run(_main(args.host, args.port, api_gateway_host, args.api_gateway_port))


if __name__ == "__main__":  # pragma: no cover
    main()
