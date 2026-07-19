"""The only GameObserver (see model/game_state.py) that exists purely to
feed events/bus.py's Bus - GameEngine's own move/jump pipeline never
changes, and never learns a bus exists (see engine/game_engine.py's own
add_observer: notify whoever is registered, then move on). Registered once
(see play.py's build_app), in place of registering each individual
consumer (move log, score, sound, animations) directly - they subscribe to
the bus instead, so a new consumer never needs GameEngine.add_observer'd
at all, only bus.subscribe'd.
"""

from model.game_state import ArrivalEvent, GameObserver, MoveLoggedEvent
from model.piece import KING
from events.bus import ARRIVAL, GAME_ENDED, MOVE_LOGGED, Bus


class BusBridge(GameObserver):
    def __init__(self, bus: Bus):
        self._bus = bus

    def on_move_logged(self, event: MoveLoggedEvent) -> None:
        self._bus.publish(MOVE_LOGGED, event)

    def on_arrival(self, event: ArrivalEvent) -> None:
        self._bus.publish(ARRIVAL, event)

        # GameEngine's own game_over flag flips true right after this same
        # notification (see engine/game_engine.py's wait()), but never
        # notifies anyone that it happened - only KingCaptureWinCondition
        # knows a king capture is what ends this variant (see
        # rules/rule_engine.py), so that's inferred here the same way
        # server/session.py's own _KingCaptureWatcher does, rather than
        # GameEngine itself being changed to publish it.
        if event.captured_piece is not None and event.captured_piece.kind == KING:
            self._bus.publish(GAME_ENDED, event)
