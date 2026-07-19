"""Generic pub/sub bus - decouples anything that reacts to the game
(scores, move log, sound, animations, ...) from GameEngine's own narrow
GameObserver interface (see model/game_state.py). GameEngine itself never
learns this exists - events/bus_bridge.py is the one GameObserver that
translates its on_move_logged/on_arrival calls into publish() here instead.

Topic names are the shared vocabulary every publisher/subscriber in this
package agrees on - kept here, alongside Bus itself, rather than scattered
across bus_bridge.py/observers.py/sound.py/game_animations.py.
"""

from collections import defaultdict
from typing import Any, Callable, DefaultDict, List

MOVE_LOGGED = "move_logged"
ARRIVAL = "arrival"
GAME_STARTED = "game_started"
GAME_ENDED = "game_ended"


class Bus:
    def __init__(self):
        self._subscribers: DefaultDict[str, List[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Callable[[Any], None]) -> None:
        self._subscribers[topic].append(handler)

    # event is passed through as-is (a MoveLoggedEvent/ArrivalEvent, or None
    # for the game_started/game_ended topics, which carry no payload of
    # their own) - the bus itself has no opinion on shape, only on topic.
    def publish(self, topic: str, event: Any = None) -> None:
        for handler in self._subscribers[topic]:
            handler(event)
