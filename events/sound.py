"""Sound cues wired to events/bus.py's Bus - which cue plays for which
event, entirely decoupled from whatever eventually plays it. No audio
library/asset dependency yet: _play() is the one seam a real audio backend
(e.g. pygame.mixer) fills in later - every other line here (which event
maps to which cue name) doesn't change when that happens.
"""

from typing import List

from model.game_state import ArrivalEvent, MoveLoggedEvent
from events.bus import Bus
from events.game_events import GameEndedEvent, GameStartedEvent

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
        bus.subscribe(MoveLoggedEvent, self._on_move_logged)
        bus.subscribe(ArrivalEvent, self._on_arrival)
        bus.subscribe(GameStartedEvent, self._on_game_started)
        bus.subscribe(GameEndedEvent, self._on_game_ended)

    def _on_move_logged(self, event: MoveLoggedEvent) -> None:
        self._play(JUMP_CUE if event.is_jump else MOVE_CUE)

    def _on_arrival(self, event: ArrivalEvent) -> None:
        if event.captured_piece is not None:
            self._play(CAPTURE_CUE)

    def _on_game_started(self, _event: GameStartedEvent) -> None:
        self._play(GAME_START_CUE)

    def _on_game_ended(self, _event: GameEndedEvent) -> None:
        self._play(GAME_END_CUE)

    def _play(self, cue_name: str) -> None:
        self.played.append(cue_name)
