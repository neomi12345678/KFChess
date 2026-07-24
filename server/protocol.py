"""Server-only translation from a decoded wire message to the engine-facing
Command shape server/session.py's GameSession.apply_command expects - the
one place a MoveMessage/JumpMessage (protocol/game_messages.py, decoded off
the wire by server/ws_server.py through protocol.registry.decode_json_message
- the same one decode path every message in either direction goes through,
see protocol/__init__.py's own docstring) turns into a Command.

Kept as its own small module rather than folded into server/router.py or
server/session.py: GameSession's own apply_command(Command) signature
predates the wire format switch to JSON-registered messages and is still
the shape tests/unit/test_server_session.py builds by hand - this is the
one adapter between that shape and the wire message a real connection
actually sends. Command itself carries a real Position, not the {"row",
"col"} dict MoveMessage/JumpMessage carry on the wire (see
protocol/game_messages.py's own docstring on why) - command_from_message is
the one place that gap is closed.
"""

from dataclasses import dataclass
from typing import Optional, Union

from model.position import Position
from protocol.game_messages import JumpMessage, MoveMessage
from protocol.snapshot_codec import position_from_json
from protocol.types import JUMP, MOVE


@dataclass(frozen=True)
class Command:
    color: str
    kind: str
    source: Position
    destination: Optional[Position]


def command_from_message(message: Union[MoveMessage, JumpMessage]) -> Command:
    if isinstance(message, JumpMessage):
        return Command(color=message.color, kind=JUMP, source=position_from_json(message.source), destination=None)

    return Command(
        color=message.color,
        kind=MOVE,
        source=position_from_json(message.source),
        destination=position_from_json(message.destination),
    )
