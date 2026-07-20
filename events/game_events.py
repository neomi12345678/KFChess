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
