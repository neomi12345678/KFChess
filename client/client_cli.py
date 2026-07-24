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
from typing import Optional, Type, Union

import websockets

from boardio.algebraic_notation import parse_square
from client.network_client import SnapshotBroadcast, decode_incoming
from protocol.game_messages import GameOverMessage, JumpMessage, MoveMessage, SeatMessage, build_jump, build_move
from protocol.lobby_messages import (
    CancelRoomMessage,
    CreateRoomMessage,
    JoinRoomMessage,
    LoginAckMessage,
    LoginMessage,
    PlayMessage,
)
from protocol.registry import encode_json_message
from protocol.types import HOST, PORT

_PLAY_INPUT = "play"
_CREATE_ROOM_INPUT = "create room"
_CANCEL_ROOM_INPUT = "cancel room"
_JOIN_ROOM_PREFIX = "join room "


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


async def _read_commands(websocket, state: _ClientState) -> None:
    loop = asyncio.get_event_loop()
    while True:
        raw = await loop.run_in_executor(None, input, "> ")
        text = raw.strip()
        lowered = text.lower()

        if lowered == _PLAY_INPUT:
            await websocket.send(encode_json_message(PlayMessage()))
            continue

        if lowered == _CREATE_ROOM_INPUT:
            await websocket.send(encode_json_message(CreateRoomMessage()))
            continue

        if lowered == _CANCEL_ROOM_INPUT:
            await websocket.send(encode_json_message(CancelRoomMessage()))
            continue

        if lowered.startswith(_JOIN_ROOM_PREFIX):
            room_id = text[len(_JOIN_ROOM_PREFIX):].strip()
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
    return parser.parse_args()


async def _main(host: str, port: int) -> None:  # pragma: no cover
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")

    uri = f"ws://{host}:{port}"
    async with websockets.connect(uri) as websocket:
        await websocket.send(encode_json_message(LoginMessage(username=username, password=password)))
        login_ack = await _recv_of_type(websocket, LoginAckMessage)
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

        await asyncio.gather(_print_incoming(websocket, state), _read_commands(websocket, state))


def main() -> None:  # pragma: no cover
    args = _parse_args()
    asyncio.run(_main(args.host, args.port))


if __name__ == "__main__":  # pragma: no cover
    main()
