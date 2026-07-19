"""Minimal shell client for the KFChess server: prompts for a username and
password in the terminal (the Home screen's own "do it in a shell, not via
GUI" login step - see server/ws_server.py's LOGIN handling, checked against
server/accounts.py's SQLite-backed accounts), then type "play" to enter
matchmaking and, once matched, moves by hand. A stand-in until the real GUI
talks to the server directly, not a replacement for it.

Run: python -m server.client_cli
"""

import asyncio
import getpass
import json
from typing import Optional

import websockets

from model.piece import BLACK, WHITE
from server.main import HOST, PORT

_SEAT_LETTER = {WHITE: "W", BLACK: "B"}
_PLAY_INPUT = "play"


class InputError(Exception):
    """Raised when a typed line doesn't match any input shape below."""


# The seat this connection is currently playing, if any - unknown until a
# "seat" message arrives (see _ClientState.observe), since matchmaking (not
# login) is what assigns one now. A plain mutable holder so _print_incoming
# (which sees that message) and _read_commands (which needs the seat to
# build a move) can share the one piece of state that changes after login.
class _ClientState:
    def __init__(self, seat: Optional[str] = None):
        self.seat = seat

    def observe(self, payload: dict) -> None:
        if payload.get("type") == "seat":
            self.seat = payload["color"]
        elif payload.get("type") == "game_over":
            self.seat = None


# Typed shorthand -> wire command (see server/protocol.py). The connection's
# own color is implicit (whichever seat matchmaking assigned), so a player
# never has to type "W"/"B" themselves:
#   "e2e4"     -> move
#   "jump e4"  -> jump
def build_command(raw_input: str, seat: str) -> str:
    text = raw_input.strip()
    if not text:
        raise InputError("empty input")

    letter = _SEAT_LETTER[seat]
    parts = text.split(None, 1)

    if parts[0].lower() == "jump":
        if len(parts) < 2 or not parts[1].strip():
            raise InputError("jump requires a square, e.g. 'jump e4'")
        return f"{letter}J{parts[1].strip()}"

    return f"{letter}{text}"


def build_login(username: str, password: str) -> str:
    return f"LOGIN {username} {password}"


def build_play() -> str:
    return "PLAY"


# A connection's own reply to something it just sent (login_ack, play_ack,
# ack) and the tick loop's periodic broadcast/countdown are written by two
# independent tasks on the server (see server/ws_server.py) - either can
# land first, so this reads past any interleaved broadcast instead of
# assuming the very next message is the one being waited for.
async def _recv_of_type(websocket, message_type: str) -> dict:
    while True:
        message = json.loads(await websocket.recv())
        if message.get("type") == message_type:
            return message


async def _print_incoming(websocket, state: _ClientState) -> None:
    async for message in websocket:
        payload = json.loads(message)
        state.observe(payload)
        if "type" in payload:  # a broadcast snapshot (see snapshot_to_json) has none
            print(payload)


async def _read_commands(websocket, state: _ClientState) -> None:
    loop = asyncio.get_event_loop()
    while True:
        raw = await loop.run_in_executor(None, input, "> ")
        text = raw.strip()

        if text.lower() == _PLAY_INPUT:
            await websocket.send(build_play())
            continue

        if state.seat is None:
            print("(not seated yet - type 'play' to find a match)")
            continue

        try:
            command = build_command(text, state.seat)
        except InputError as error:
            print(f"(ignored: {error})")
            continue
        await websocket.send(command)


async def _main() -> None:  # pragma: no cover
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")

    uri = f"ws://{HOST}:{PORT}"
    async with websockets.connect(uri) as websocket:
        await websocket.send(build_login(username, password))
        login_ack = await _recv_of_type(websocket, "login_ack")
        if not login_ack["accepted"]:
            print(f"Login failed: {login_ack['reason']}")
            return
        print(f"Logged in as {login_ack['username']} (rating {login_ack['rating']})")

        if login_ack.get("reconnected"):
            state = _ClientState(seat=login_ack["color"])
            print(f"Reconnected to your game as {state.seat}")
        else:
            state = _ClientState()
            print("Type 'play' to find a match.")

        await asyncio.gather(_print_incoming(websocket, state), _read_commands(websocket, state))


def main() -> None:  # pragma: no cover
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
