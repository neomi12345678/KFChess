"""Game start/end animation cues wired to events/bus.py's Bus - decoupled
from whatever eventually renders them. No real animation asset/timeline
yet: _trigger() is the one seam a real renderer hook (e.g. telling
view/renderer.py to play a banner/fade) fills in later - this only ever
decides *when* to fire one, never how it looks.
"""

from typing import List, Optional

from model.game_state import ArrivalEvent
from events.bus import GAME_ENDED, GAME_STARTED, Bus

GAME_START_ANIMATION = "game_start"
GAME_END_ANIMATION = "game_end"


class GameAnimationCues:
    def __init__(self, bus: Bus):
        # Every animation this instance would have triggered, in order -
        # the placeholder seam tests exercise for real (see _trigger()) in
        # place of an actual renderer/asset hook.
        self.triggered: List[str] = []
        bus.subscribe(GAME_STARTED, self._on_game_started)
        bus.subscribe(GAME_ENDED, self._on_game_ended)

    def _on_game_started(self, _event: None) -> None:
        self._trigger(GAME_START_ANIMATION)

    def _on_game_ended(self, _event: Optional[ArrivalEvent]) -> None:
        self._trigger(GAME_END_ANIMATION)

    def _trigger(self, animation_name: str) -> None:
        self.triggered.append(animation_name)
