"""Lobby-family wire vocabulary: the login/matchmaking/room messages a
client sends (LoginMessage/PlayMessage/CreateRoomMessage/CancelRoomMessage/
JoinRoomMessage), and the dataclasses the server acks each of them with.
Every class here registers itself with registry.register() right where
it's defined - see registry.py's own docstring for why, and for
message_to_dict/encode_json_message/decode_json_message, the same
encode/decode pair both directions (this family and game_messages.py's)
share.

game_messages.py holds the sibling family for in-game (not lobby) traffic:
moves/jumps/captures/game-over/disconnects.
"""

from dataclasses import dataclass
from typing import Optional

from protocol.registry import register
from protocol.types import (
    CANCEL_ROOM,
    CANCEL_ROOM_ACK,
    CREATE_ROOM,
    CREATE_ROOM_ACK,
    JOIN_ROOM,
    JOIN_ROOM_ACK,
    LOGIN,
    LOGIN_ACK,
    MATCHMAKING_TIMEOUT,
    PLAY,
    PLAY_ACK,
    Role,
)


@register(LOGIN)
@dataclass(frozen=True)
class LoginMessage:
    username: str
    password: str
    type: str = LOGIN


@register(PLAY)
@dataclass(frozen=True)
class PlayMessage:
    type: str = PLAY


@register(CREATE_ROOM)
@dataclass(frozen=True)
class CreateRoomMessage:
    type: str = CREATE_ROOM


@register(CANCEL_ROOM)
@dataclass(frozen=True)
class CancelRoomMessage:
    type: str = CANCEL_ROOM


@register(JOIN_ROOM)
@dataclass(frozen=True)
class JoinRoomMessage:
    room_id: str
    type: str = JOIN_ROOM


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
