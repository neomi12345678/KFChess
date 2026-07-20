"""Game start/end animation cues wired to events/bus.py's Bus - decoupled
from whatever eventually renders them. No real animation asset/timeline
yet: _trigger() is the one seam a real renderer hook (e.g. telling
view/renderer.py to play a banner/fade) fills in later - this only ever
decides *when* to fire one, never how it looks.
"""

from typing import List

from events.bus import Bus
from events.game_events import GameEndedEvent, GameStartedEvent

GAME_START_ANIMATION = "game_start"
GAME_END_ANIMATION = "game_end"


class GameAnimationCues:
    def __init__(self, bus: Bus):
        # Every animation this instance would have triggered, in order -
        # the placeholder seam tests exercise for real (see _trigger()) in
        # place of an actual renderer/asset hook.
        self.triggered: List[str] = []
        bus.subscribe(GameStartedEvent, self._on_game_started)
        bus.subscribe(GameEndedEvent, self._on_game_ended)

    def _on_game_started(self, _event: GameStartedEvent) -> None:
        self._trigger(GAME_START_ANIMATION)

    def _on_game_ended(self, _event: GameEndedEvent) -> None:
        self._trigger(GAME_END_ANIMATION)

    def _trigger(self, animation_name: str) -> None:
        self.triggered.append(animation_name)
