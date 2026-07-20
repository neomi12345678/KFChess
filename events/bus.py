"""Generic pub/sub bus - decouples anything that reacts to the game
(scores, move log, sound, animations, ...) from GameEngine's own narrow
GameObserver interface (see model/game_state.py). GameEngine itself never
learns this exists - events/bus_bridge.py is the one GameObserver that
translates its on_move_logged/on_arrival calls into publish() here instead.

Dispatch is keyed by type(event), not by a string topic name: a publisher
never has to agree on a shared name with its subscribers, only on which
class it publishes - MoveLoggedEvent/ArrivalEvent (model/game_state.py) or
GameStartedEvent/GameEndedEvent (events/game_events.py). The bus itself has
no opinion on any of those shapes, only on the type of whatever is handed
to publish().
"""

from collections import defaultdict
from typing import Any, Callable, DefaultDict, List, Type


class Bus:
    def __init__(self):
        self._subscribers: DefaultDict[Type, List[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, event_type: Type, handler: Callable[[Any], None]) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, event: Any) -> None:
        for handler in self._subscribers[type(event)]:
            handler(event)
