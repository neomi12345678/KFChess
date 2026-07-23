"""Aggregates everything view/renderer.py's Renderer needs to draw one frame
into a single immutable value, built once per frame by build_ui_snapshot()
below. Before this existed, Renderer held long-lived references to
MoveLogObserver/ScoreObserver (or protocol/panel_state.py's PanelState stand-in)
and pulled from them mid-draw - now Renderer.draw() takes one self-contained
value and never reaches out to a live collaborator itself, which is what
lets it be exercised with nothing but plain data in tests.

Lives under view/, not events/: unlike MoveLogObserver/ScoreObserver
themselves (derived application state, a peer of view/ - see their own
docstring), this is purely "what does Renderer need for one frame",
assembled from whatever the caller (app.py, play_online.py) already has
on hand.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol

from events.observers import MoveLogEntry
from model.game_state import GameSnapshot
from model.piece import BLACK, WHITE

_PANEL_COLORS = (WHITE, BLACK)


# The shape a moves-log entry must have for _draw_panel to read it - not
# MoveLogEntry itself, since protocol.panel_state.PanelState's own entries
# (_PanelMoveLine) are a different concrete class with the same two fields
# and no business importing events.observers just to satisfy this.
class MoveLogEntryLike(Protocol):
    notation: str
    elapsed_ms: int


# The two duck-typed collaborators build_ui_snapshot below accepts - formal
# stand-ins for events.observers.MoveLogObserver/ScoreObserver (real local
# play) and protocol.panel_state.PanelState (the client-side networked-play stand-in
# described in its own docstring), so a signature drift between the two
# implementations is a type-checking error here instead of only a runtime
# AttributeError wherever build_ui_snapshot happens to be called.
class MoveLogSource(Protocol):
    def entries_for(self, color: str) -> List[MoveLogEntryLike]: ...


class ScoreSource(Protocol):
    def score_for(self, color: str) -> int: ...


@dataclass(frozen=True)
class UiSnapshot:
    game: GameSnapshot
    status_message: Optional[str] = None
    move_log_by_color: Dict[str, List[MoveLogEntry]] = field(default_factory=dict)
    score_by_color: Dict[str, int] = field(default_factory=dict)


# move_log/score are duck-typed (entries_for(color)/score_for(color)) so
# either the real events.observers.MoveLogObserver/ScoreObserver or
# protocol.panel_state.PanelState's client-side stand-in works here unchanged -
# both None by default, matching Renderer's own former no-panels default,
# so a caller that doesn't track either still gets a valid UiSnapshot.
def build_ui_snapshot(
    game: GameSnapshot,
    move_log: Optional[MoveLogSource] = None,
    score: Optional[ScoreSource] = None,
    status_message: Optional[str] = None,
) -> UiSnapshot:
    return UiSnapshot(
        game=game,
        status_message=status_message,
        move_log_by_color=(
            {color: move_log.entries_for(color) for color in _PANEL_COLORS} if move_log is not None else {}
        ),
        score_by_color=({color: score.score_for(color) for color in _PANEL_COLORS} if score is not None else {}),
    )
