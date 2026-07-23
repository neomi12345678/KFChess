"""In-game wire vocabulary: the move/jump command text a client builds and
sends (build_move/build_jump - see server/protocol.py's parse_command,
which parses these back apart server-side), and the dataclasses the server
sends for everything that happens once a game is running (acks, captures,
disconnects, game-over). Each registers itself with registry.register()
the same way lobby_messages.py's do - see registry.py's own docstring.

lobby_messages.py holds the sibling family for login/matchmaking/room
traffic.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from protocol.registry import register
from protocol.types import (
    ACK,
    CAPTURE,
    COLOR_PREFIX,
    DISCONNECT_COUNTDOWN,
    ERROR,
    GAME_OVER,
    MOVE_LOGGED,
    SEAT,
)


def build_move(color: str, source: str, destination: str) -> str:
    return f"{COLOR_PREFIX[color]}{source}{destination}"


def build_jump(color: str, square: str) -> str:
    return f"{COLOR_PREFIX[color]}J{square}"


@register(ERROR)
@dataclass(frozen=True)
class ErrorMessage:
    message: str
    type: str = ERROR


@register(ACK)
@dataclass(frozen=True)
class AckMessage:
    accepted: bool
    reason: str
    type: str = ACK


@register(SEAT)
@dataclass(frozen=True)
class SeatMessage:
    color: str
    type: str = SEAT


@register(DISCONNECT_COUNTDOWN)
@dataclass(frozen=True)
class DisconnectCountdownMessage:
    seat: str
    seconds_remaining: int
    type: str = DISCONNECT_COUNTDOWN


@register(GAME_OVER)
@dataclass(frozen=True)
class GameOverMessage:
    ratings: Dict[str, int]
    type: str = GAME_OVER


@register(MOVE_LOGGED)
@dataclass(frozen=True)
class MoveLoggedMessage:
    is_jump: bool
    type: str = MOVE_LOGGED


@register(CAPTURE)
@dataclass(frozen=True)
class CaptureMessage:
    type: str = CAPTURE
