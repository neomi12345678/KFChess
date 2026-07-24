"""Client-side read model for the per-tick panel broadcast - see
snapshot_codec.py's panel_to_json for the wire shape this rebuilds from.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class _PanelMoveLine:
    notation: str
    elapsed_ms: int


# Client-side duck-typed stand-in for events.observers.MoveLogObserver +
# ScoreObserver - view/renderer.py only ever calls entries_for(color)/
# score_for(color) on whatever it's given (see Renderer._draw_panel), so a
# single instance of this satisfies both roles at once, rebuilt from
# panel_to_json's wire payload on every broadcast. The real observers build
# their state from a live GameEngine event stream that never crosses the
# network (see play_online.py) - this is just their last-broadcast snapshot.
class PanelState:
    def __init__(self):
        self._entries_by_color: dict = {}
        self._score_by_color: dict = {}
        self._name_by_color: dict = {}

    def update_from_json(self, payload: dict) -> None:
        self._entries_by_color = {
            color: [_PanelMoveLine(notation=entry["notation"], elapsed_ms=entry["elapsed_ms"]) for entry in entries]
            for color, entries in payload["move_log"].items()
        }
        self._score_by_color = payload["score"]
        # .get, not a bare payload["names"] - payload may be an older/other
        # caller's panel_to_json() dict (or a hand-built test fixture, see
        # tests/unit/test_command_translation.py) from before "names" existed.
        self._name_by_color = payload.get("names", {})

    def entries_for(self, color: str) -> List[_PanelMoveLine]:
        return self._entries_by_color.get(color, [])

    def score_for(self, color: str) -> int:
        return self._score_by_color.get(color, 0)

    # None (not a placeholder like "White"/color itself) when this color's
    # real name hasn't been told to us - see view/renderer.py's Renderer,
    # which treats a missing name the same way: no name line at all rather
    # than a guess.
    def name_for(self, color: str) -> Optional[str]:
        return self._name_by_color.get(color)
