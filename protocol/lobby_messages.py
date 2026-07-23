"""Lobby-family wire vocabulary: the login/matchmaking/room commands a
client builds and sends as plain text (build_login/build_play/
build_create_room/build_cancel_room/build_join_room - see
server/protocol.py's parse_login/is_play_command/is_create_room_command/
is_cancel_room_command/parse_join_room, which parse these back apart
server-side), and the dataclasses the server acks each of them with. Each
ack class registers itself with registry.register() right where it's
defined - see registry.py's own docstring for why.

game_messages.py holds the sibling family for in-game (not lobby) traffic:
moves/jumps/captures/game-over/disconnects.
"""

from dataclasses import dataclass
from typing import Optional

from protocol.registry import register
from protocol.types import (
    CANCEL_ROOM_ACK,
    CREATE_ROOM_ACK,
    JOIN_ROOM_ACK,
    LOGIN_ACK,
    MATCHMAKING_TIMEOUT,
    PLAY_ACK,
    Role,
)


def build_login(username: str, password: str) -> str:
    return f"LOGIN {username} {password}"


def build_play() -> str:
    return "PLAY"


def build_create_room() -> str:
    return "CREATE_ROOM"


def build_cancel_room() -> str:
    return "CANCEL_ROOM"


def build_join_room(room_id: str) -> str:
    return f"JOIN_ROOM {room_id}"


# One dataclass per server->client control message. Each mirrors its
# message's exact real-world shape: a field is only Optional/defaulted if
# that message genuinely sends it sometimes and omits it other times (see
# server/connections.py's ConnectionRegistry.send, which drops None fields
# before serializing so the wire shape is unchanged from before these
# existed) - a field with no default is one every send site actually
# provides. Building one of these with a missing required field or a typo'd
# keyword argument is a TypeError at the send site, not a message a client
# silently never matches anything in.
@register(LOGIN_ACK)
@dataclass(frozen=True)
class LoginAckMessage:
    accepted: bool
    reason: Optional[str] = None
    username: Optional[str] = None
    rating: Optional[int] = None
    reconnected: Optional[bool] = None
    color: Optional[str] = None
    resuming_room_id: Optional[str] = None
    type: str = LOGIN_ACK


@register(PLAY_ACK)
@dataclass(frozen=True)
class PlayAckMessage:
    accepted: bool
    reason: str
    type: str = PLAY_ACK


@register(CREATE_ROOM_ACK)
@dataclass(frozen=True)
class CreateRoomAckMessage:
    accepted: bool
    reason: Optional[str] = None
    room_id: Optional[str] = None
    type: str = CREATE_ROOM_ACK


@register(JOIN_ROOM_ACK)
@dataclass(frozen=True)
class JoinRoomAckMessage:
    accepted: bool
    reason: Optional[str] = None
    room_id: Optional[str] = None
    role: Optional[Role] = None
    type: str = JOIN_ROOM_ACK


@register(CANCEL_ROOM_ACK)
@dataclass(frozen=True)
class CancelRoomAckMessage:
    accepted: bool
    reason: Optional[str] = None
    type: str = CANCEL_ROOM_ACK


@register(MATCHMAKING_TIMEOUT)
@dataclass(frozen=True)
class MatchmakingTimeoutMessage:
    type: str = MATCHMAKING_TIMEOUT
