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


# Sent instead of LoginMessage once a client has already authenticated over
# REST (see services/api_gateway/main.py's POST /login, and
# client/network_client.py's own api_gateway_port-gated login()) - no
# password, since that already happened. Attaches this websocket to
# username the same way LoginMessage's own connection-registration half
# does (see server/ws_server.py's _handle_identify), and, if username is
# mid-game and was marked disconnected, reconnects it into that live
# GameSession (server/router.py's CommandRouter.decide_identify) - the one
# piece of LoginMessage's three branches this narrower message replicates;
# it does not replicate the room-survived-a-restart branch (see that
# method's own docstring).
#
# token is the session token LoginAckMessage handed back on the LOGIN/POST
# /login that preceded this - proof this username was actually
# authenticated a moment ago, not just asserted (see server/accounts.py's
# issue_session_token/verify_session_token). Optional only so a client that
# omits it decodes cleanly into an explicit INVALID_SESSION rejection in
# _handle_identify, rather than a raw TypeError at the wire gatekeeper.
@register(MessageType.IDENTIFY)
@dataclass(frozen=True)
class IdentifyMessage:
    username: str
    token: Optional[str] = None
    type: str = MessageType.IDENTIFY


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
    # Set (via server/accounts.py's issue_session_token) whenever
    # accepted=True - the credential a client attaches to every later
    # IdentifyMessage to prove it, rather than just assert, which username
    # it is. None whenever accepted=False, since no session exists to prove.
    token: Optional[str] = None
    type: str = MessageType.LOGIN_ACK


# decide_identify's own docstring explains why *its own* decision is always
# accepted - that's a separate fact from whether this message ever carries
# accepted=False: _handle_identify (server/ws_server.py) now rejects an
# IdentifyMessage with a missing/invalid/expired token before decide_identify
# is ever reached, via this same message with accepted=False and a reason
# (see protocol/types.py's Reason.INVALID_SESSION).
@register(MessageType.IDENTIFY_ACK)
@dataclass(frozen=True)
class IdentifyAckMessage:
    accepted: bool
    reason: Optional[str] = None
    type: str = MessageType.IDENTIFY_ACK


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


# Periodic "still searching" heartbeat sent while a PLAY match is queued -
# see server/matchmaking.py's own MATCHMAKING_STATUS_INTERVAL_MS - not sent
# every tick, and never sent once MatchmakingTimeoutMessage/SeatMessage ends
# the wait.
@register(MessageType.MATCHMAKING_STATUS)
@dataclass(frozen=True)
class MatchmakingStatusMessage:
    seconds_remaining: int
    type: str = MessageType.MATCHMAKING_STATUS
