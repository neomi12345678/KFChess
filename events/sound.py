"""Sound cues wired to events/bus.py's Bus - which cue plays for which
event, entirely decoupled from whatever eventually plays it. No audio
library/asset dependency yet: _play() is the one seam a real audio backend
(e.g. pygame.mixer) fills in later - every other line here (which event
maps to which cue name) doesn't change when that happens.
"""

from typing import List, Optional

from model.game_state import ArrivalEvent, MoveLoggedEvent
from events.bus import ARRIVAL, GAME_ENDED, GAME_STARTED, MOVE_LOGGED, Bus

MOVE_CUE = "move"
JUMP_CUE = "jump"
CAPTURE_CUE = "capture"
GAME_START_CUE = "game_start"
GAME_END_CUE = "game_end"


class SoundCues:
    def __init__(self, bus: Bus):
        # Every cue this instance would have played, in order - the
        # placeholder seam tests exercise for real (see _play()) in place
        # of an actual audio device/asset file.
        self.played: List[str] = []
        bus.subscribe(MOVE_LOGGED, self._on_move_logged)
        bus.subscribe(ARRIVAL, self._on_arrival)
        bus.subscribe(GAME_STARTED, self._on_game_started)
        bus.subscribe(GAME_ENDED, self._on_game_ended)

    def _on_move_logged(self, event: MoveLoggedEvent) -> None:
        self._play(JUMP_CUE if event.is_jump else MOVE_CUE)

    def _on_arrival(self, event: ArrivalEvent) -> None:
        if event.captured_piece is not None:
            self._play(CAPTURE_CUE)

    def _on_game_started(self, _event: None) -> None:
        self._play(GAME_START_CUE)

    def _on_game_ended(self, _event: Optional[ArrivalEvent]) -> None:
        self._play(GAME_END_CUE)

    def _play(self, cue_name: str) -> None:
        self.played.append(cue_name)
