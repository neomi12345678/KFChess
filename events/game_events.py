"""Event classes for the two moments in a game's lifecycle that carry no
natural payload of their own from GameEngine - unlike MoveLoggedEvent/
ArrivalEvent (model/game_state.py), which GameEngine's move/jump pipeline
already produces. Kept as real, distinct types (not plain None, and not a
reused ArrivalEvent) so events/bus.py's type(event)-keyed dispatch can tell
"a piece arrived" (ArrivalEvent) apart from "that arrival just ended the
game" (GameEndedEvent), even though events/bus_bridge.py derives the second
from the same ArrivalEvent instance as the first.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from model.game_state import ArrivalEvent


@dataclass(frozen=True)
class GameStartedEvent:
    pass


@dataclass(frozen=True)
class GameEndedEvent:
    # The king-capture ArrivalEvent that ended the game - see
    # events/bus_bridge.py's on_arrival for why "game over" is inferred
    # from a king capture there, rather than GameEngine reporting it itself.
    arrival: ArrivalEvent
    # {color: new_rating}, only ever set by client/network_message_adapter.py's
    # NetworkMessageAdapter from the server's own "game_over" wire message -
    # a local game (events/bus_bridge.py's own GameEndedEvent(arrival=event))
    # has no ELO to report, so this stays None there.
    new_ratings: Optional[Dict[str, int]] = None


@dataclass(frozen=True)
class RemoteCaptureEvent:
    """A capture just happened, reported by client/network_message_adapter.py's
    NetworkMessageAdapter from the server's own "capture" wire message (see
    server/publisher.py's NetworkPublisher) - unlike a local GameEngine's own
    ArrivalEvent (model/game_state.py), the wire carries no piece identity,
    board position, or the real captured Piece, so there's no ArrivalEvent
    to reconstruct even a placeholder for. Subscribers that only ever check
    "did a capture happen" (SoundCues) treat this the same as an ArrivalEvent
    whose captured_piece isn't None."""


@dataclass(frozen=True)
class RemoteMoveEvent:
    """A move or jump was just logged, reported by client/network_message_adapter.py's
    NetworkMessageAdapter from the server's own "move_logged" wire message - unlike a
    local GameEngine's own MoveLoggedEvent (model/game_state.py), the wire carries only
    whether it was a jump, none of the other move-log fields (color, notation, piece
    identity, elapsed time, ...), so there's no real MoveLoggedEvent to reconstruct even
    a placeholder for. Subscribers that only ever need is_jump (SoundCues) treat this
    the same as a MoveLoggedEvent."""

    is_jump: bool
