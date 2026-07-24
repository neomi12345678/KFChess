"""Shared domain-event wiring for a freshly built game: the Bus, its
move-log/score observers, and the BusBridge that's the only GameObserver
GameEngine itself ever sees. This is the one place that answers "how do you
hook a GameEngine up to the domain-event system" - both a local game
(app_builder.py's build_app) and a networked one (server/session.py's
GameSession) need the exact same answer, so it lives here once instead of
being copy-pasted between them.

Deliberately doesn't publish GameStartedEvent itself, unlike everything else
this wires: each caller still has its own additional subscribers to register
first (app_builder.py's SoundCues/GameAnimationCues; server/session.py's own
king-capture watcher) before that event goes out, so the publish has to stay
the caller's own last step, not something this helper does on their behalf.
"""

from typing import Tuple

from engine.game_engine import GameEngine
from events.bus import Bus
from events.bus_bridge import BusBridge
from events.observers import MoveLogObserver, ScoreObserver
from model.game_state import ArrivalEvent, MoveLoggedEvent


def wire_game_events(game_engine: GameEngine, board_height: int) -> Tuple[Bus, MoveLogObserver, ScoreObserver]:
    bus = Bus()
    move_log = MoveLogObserver(board_height=board_height)
    score = ScoreObserver()
    bus.subscribe(MoveLoggedEvent, move_log.on_move_logged)
    bus.subscribe(ArrivalEvent, move_log.on_arrival)
    bus.subscribe(ArrivalEvent, score.on_arrival)
    game_engine.add_observer(BusBridge(bus))
    return bus, move_log, score
