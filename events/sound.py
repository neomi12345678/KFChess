"""Sound cues wired to events/bus.py's Bus - which cue plays for which
event, entirely decoupled from whatever eventually plays it. _play()
is the one seam a real audio backend fills in - every other line here
(which event maps to which cue name) doesn't change when that does.

winsound (Windows-only, stdlib) is that backend, not pygame.mixer - valid
because the side that ever plays sound is always the client (Windows),
never the server (see docs/kf-chess-architecture-plan.md's own reasoning
for the same choice): if the server ever runs on Linux it's irrelevant,
since it never plays sound at all.
"""

import pathlib
import sys
from typing import Dict, List, Optional

from model.game_state import ArrivalEvent, MoveLoggedEvent
from events.bus import Bus
from events.game_events import GameEndedEvent, GameStartedEvent, RemoteCaptureEvent

MOVE_CUE = "move"
JUMP_CUE = "jump"
CAPTURE_CUE = "capture"
GAME_START_CUE = "game_start"
GAME_END_CUE = "game_end"

SOUNDS_DIR = pathlib.Path(__file__).resolve().parent.parent / "sounds"

# Not every cue has its own asset - there's no dedicated jump/game-start
# recording, so those two intentionally fall back to the closest existing
# one (JUMP_CUE reuses the plain move sound) or play nothing at all
# (GAME_START_CUE has no mapping here, so _play silently no-ops for it).
_CUE_TO_FILENAME: Dict[str, str] = {
    MOVE_CUE: "move.wav",
    JUMP_CUE: "move.wav",
    CAPTURE_CUE: "capture.wav",
    GAME_END_CUE: "game_over.wav",
}

if sys.platform == "win32":
    import winsound
else:
    winsound = None


def _path_for(cue_name: str) -> Optional[pathlib.Path]:
    filename = _CUE_TO_FILENAME.get(cue_name)
    if filename is None:
        return None
    path = SOUNDS_DIR / filename
    return path if path.is_file() else None


# The actual audio-playing seam, standalone rather than a SoundCues method -
# play_online.py's own cue selection (see its own docstring) has no domain
# events to subscribe a SoundCues instance to at all, only wire snapshots
# and move-log notation strings to derive a cue name from client-side, but
# it still needs this exact same "play this cue" seam SoundCues.play uses,
# not a second, divergent implementation of it.
def play_cue(cue_name: str) -> None:
    path = _path_for(cue_name)
    if path is not None and winsound is not None:
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)


class SoundCues:
    def __init__(self, bus: Bus):
        # Every cue this instance has played, in order - lets tests assert
        # on cue selection without a real audio device (see play_cue()).
        self.played: List[str] = []
        bus.subscribe(MoveLoggedEvent, self._on_move_logged)
        bus.subscribe(ArrivalEvent, self._on_arrival)
        bus.subscribe(RemoteCaptureEvent, self._on_remote_capture)
        bus.subscribe(GameStartedEvent, self._on_game_started)
        bus.subscribe(GameEndedEvent, self._on_game_ended)

    def _on_move_logged(self, event: MoveLoggedEvent) -> None:
        self._play(JUMP_CUE if event.is_jump else MOVE_CUE)

    def _on_arrival(self, event: ArrivalEvent) -> None:
        if event.captured_piece is not None:
            self._play(CAPTURE_CUE)

    # Same cue as a local capture's ArrivalEvent above - see
    # events/game_events.py's RemoteCaptureEvent for why a networked capture
    # can't carry (or fake) a real ArrivalEvent's captured_piece instead.
    def _on_remote_capture(self, _event: RemoteCaptureEvent) -> None:
        self._play(CAPTURE_CUE)

    def _on_game_started(self, _event: GameStartedEvent) -> None:
        self._play(GAME_START_CUE)

    def _on_game_ended(self, _event: GameEndedEvent) -> None:
        self._play(GAME_END_CUE)

    def _play(self, cue_name: str) -> None:
        self.played.append(cue_name)
        play_cue(cue_name)
