"""In-game wire vocabulary: the move/jump commands a client sends
(MoveMessage/JumpMessage), and the dataclasses the server sends for
everything that happens once a game is running (acks, captures,
disconnects, game-over). Each registers itself with registry.register()
the same way lobby_messages.py's do - see registry.py's own docstring.

lobby_messages.py holds the sibling family for login/matchmaking/room
traffic.
"""

from dataclasses import dataclass
from typing import Dict

from model.position import Position
from protocol.registry import register
from protocol.snapshot_codec import position_to_json
from protocol.types import MessageType


# color is the seat this connection was assigned (see SeatMessage) - never
# re-derived from which connection sent it, so server/router.py's own
# "wrong_seat" check (comparing this against the seat GameLoop actually
# assigned) stays meaningful instead of a client simply asserting whichever
# color it likes. source/destination are plain {"row", "col"} dicts (see
# protocol/snapshot_codec.py's position_to_json), not a Position field
# directly - protocol/registry.py's message_from_dict rebuilds a registered
# dataclass's fields verbatim from the wire payload, with no notion of a
# field that itself needs a nested decode step, the same reason
# GameOverMessage's own ratings field below is a plain Dict[str, int] and
# not, say, a {color: RatingChange} of some other dataclass. build_move/
# build_jump are what turn a real Position into one of these;
# server/command_translation.py's command_from_message is the one place a
# decoded MoveMessage/JumpMessage turns back into a real Position, right
# before GameSession needs one.
@register(MessageType.MOVE)
@dataclass(frozen=True)
class MoveMessage:
    color: str
    source: dict
    destination: dict
    type: str = MessageType.MOVE


@register(MessageType.JUMP)
@dataclass(frozen=True)
class JumpMessage:
    color: str
    source: dict
    type: str = MessageType.JUMP


def build_move(color: str, source: Position, destination: Position) -> MoveMessage:
    return MoveMessage(color=color, source=position_to_json(source), destination=position_to_json(destination))


def build_jump(color: str, source: Position) -> JumpMessage:
    return JumpMessage(color=color, source=position_to_json(source))


@register(MessageType.ERROR)
@dataclass(frozen=True)
class ErrorMessage:
    message: str
    type: str = MessageType.ERROR


@register(MessageType.ACK)
@dataclass(frozen=True)
class AckMessage:
    accepted: bool
    reason: str
    type: str = MessageType.ACK


@register(MessageType.SEAT)
@dataclass(frozen=True)
class SeatMessage:
    color: str
    type: str = MessageType.SEAT


@register(MessageType.DISCONNECT_COUNTDOWN)
@dataclass(frozen=True)
class DisconnectCountdownMessage:
    seat: str
    seconds_remaining: int
    type: str = MessageType.DISCONNECT_COUNTDOWN


@register(MessageType.GAME_OVER)
@dataclass(frozen=True)
class GameOverMessage:
    ratings: Dict[str, int]
    type: str = MessageType.GAME_OVER


@register(MessageType.MOVE_LOGGED)
@dataclass(frozen=True)
class MoveLoggedMessage:
    is_jump: bool
    type: str = MessageType.MOVE_LOGGED


@register(MessageType.CAPTURE)
@dataclass(frozen=True)
class CaptureMessage:
    type: str = MessageType.CAPTURE
