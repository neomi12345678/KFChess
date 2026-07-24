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
from protocol.types import MessageType, Role


@register(MessageType.LOGIN)
@dataclass(frozen=True)
class LoginMessage:
    username: str
    password: str
    type: str = MessageType.LOGIN


@register(MessageType.PLAY)
@dataclass(frozen=True)
class PlayMessage:
    type: str = MessageType.PLAY


@register(MessageType.CREATE_ROOM)
@dataclass(frozen=True)
class CreateRoomMessage:
    type: str = MessageType.CREATE_ROOM


@register(MessageType.CANCEL_ROOM)
@dataclass(frozen=True)
class CancelRoomMessage:
    type: str = MessageType.CANCEL_ROOM


@register(MessageType.JOIN_ROOM)
@dataclass(frozen=True)
class JoinRoomMessage:
    room_id: str
    type: str = MessageType.JOIN_ROOM


# One dataclass per server->client control message. Each mirrors its
# message's exact real-world shape: a field is only Optional/defaulted if
# that message genuinely sends it sometimes and omits it other times (see
# server/connections.py's ConnectionRegistry.send, which drops None fields
# before serializing so the wire shape is unchanged from before these
# existed) - a field with no default is one every send site actually
# provides. Building one of these with a missing required field or a typo'd
# keyword argument is a TypeError at the send site, not a message a client
# silently never matches anything in.
@register(MessageType.LOGIN_ACK)
@dataclass(frozen=True)
class LoginAckMessage:
    accepted: bool
    reason: Optional[str] = None
    username: Optional[str] = None
    rating: Optional[int] = None
    reconnected: Optional[bool] = None
    color: Optional[str] = None
    resuming_room_id: Optional[str] = None
    type: str = MessageType.LOGIN_ACK


@register(MessageType.PLAY_ACK)
@dataclass(frozen=True)
class PlayAckMessage:
    accepted: bool
    reason: str
    type: str = MessageType.PLAY_ACK


@register(MessageType.CREATE_ROOM_ACK)
@dataclass(frozen=True)
class CreateRoomAckMessage:
    accepted: bool
    reason: Optional[str] = None
    room_id: Optional[str] = None
    type: str = MessageType.CREATE_ROOM_ACK


@register(MessageType.JOIN_ROOM_ACK)
@dataclass(frozen=True)
class JoinRoomAckMessage:
    accepted: bool
    reason: Optional[str] = None
    room_id: Optional[str] = None
    role: Optional[Role] = None
    type: str = MessageType.JOIN_ROOM_ACK


@register(MessageType.CANCEL_ROOM_ACK)
@dataclass(frozen=True)
class CancelRoomAckMessage:
    accepted: bool
    reason: Optional[str] = None
    type: str = MessageType.CANCEL_ROOM_ACK


@register(MessageType.MATCHMAKING_TIMEOUT)
@dataclass(frozen=True)
class MatchmakingTimeoutMessage:
    type: str = MessageType.MATCHMAKING_TIMEOUT
