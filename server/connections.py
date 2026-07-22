"""Tracks each logged-in username's live websocket, and is the one place in
this server that ever writes to a socket - see ConnectionRegistry.send's own
docstring for why every send in server/ws_server.py and server/game_loop.py
goes through here instead of calling websocket.send directly.
"""

import json
from dataclasses import asdict, is_dataclass
from typing import Dict, Union

import websockets

from net_protocol import ErrorMessage

# Every outgoing control message is one of net_protocol.py's frozen
# dataclasses (ErrorMessage stands in for the whole family here just for
# the type hint) - the per-tick snapshot broadcast is the one exception,
# still a plain dict from snapshot_to_json/panel_to_json (see net_protocol.py's
# own docstring on why that one has no dataclass).
WirePayload = Union[ErrorMessage, dict]


# A dataclass field only has a default (None) when that message genuinely
# omits it sometimes (see net_protocol.py's own docstring on each message) -
# stripping those Nones here, in the one place every send funnels through,
# is what keeps the actual bytes on the wire identical to before these
# dataclasses existed, so no client-side parsing needed to change.
def _as_wire_dict(payload: WirePayload) -> dict:
    if not is_dataclass(payload):
        return payload
    return {key: value for key, value in asdict(payload).items() if value is not None}


class ConnectionRegistry:
    def __init__(self):
        self._by_username: Dict[str, object] = {}

    def get(self, username: str):
        return self._by_username.get(username)

    def set(self, username: str, websocket) -> None:
        self._by_username[username] = websocket

    # True (and only then does it actually clear the entry) iff `websocket`
    # is still the one on file for `username` - a newer connection may have
    # already logged this same username back in (e.g. a client reconnecting
    # after a network blip before this stale socket's own recv loop noticed
    # it was gone), and that stale socket closing later must not evict the
    # live one. server/ws_server.py's _handle_connection gates the rest of
    # its own disconnect cleanup (matchmaking/game/room state) on this same
    # check, not just the dict write.
    def discard_if_current(self, username: str, websocket) -> bool:
        if self._by_username.get(username) is not websocket:
            return False
        self._by_username.pop(username, None)
        return True

    # Every send in this server goes through here - a connection can drop
    # between a caller reading self._by_username and actually writing to it
    # (the tick loop and a connection's own recv loop are separate tasks),
    # so every send site would otherwise need its own try/except. Catches
    # OSError alongside websockets' own ConnectionClosed - a socket the OS
    # has already torn down out from under us (observed as a raw
    # ConnectionAbortedError on Windows, not always wrapped into
    # ConnectionClosed by every code path) is exactly as harmless here as an
    # ordinary clean disconnect: this send was going to a connection that's
    # already gone either way. Left uncaught, it used to escape all the way
    # out of the tick loop and crash the *entire* server over one player's
    # dead socket - every other game along with it.
    @staticmethod
    async def send(websocket, payload: WirePayload) -> None:
        try:
            await websocket.send(json.dumps(_as_wire_dict(payload)))
        except (websockets.exceptions.ConnectionClosed, OSError):
            pass

    async def send_to_username(self, username: str, payload: WirePayload) -> None:
        websocket = self._by_username.get(username)
        if websocket is not None:
            await self.send(websocket, payload)
