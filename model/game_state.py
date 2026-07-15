from dataclasses import dataclass
from typing import List, Optional

from model.board import BoardRepresentation
from model.piece import PieceRepresentation
from model.position import Position


@dataclass
class GameState:
    board: BoardRepresentation


# Shared event/snapshot vocabulary: the engine, the real-time arbiter, and
# the view all need these shapes, so they live here instead of being
# duplicated or owned by whichever module happens to produce them first.


@dataclass
class MoveResult:
    is_accepted: bool
    reason: str


@dataclass
class JumpResult:
    is_accepted: bool
    reason: str


@dataclass
class ArrivalEvent:
    piece: PieceRepresentation
    captured_piece: Optional[PieceRepresentation]


@dataclass(frozen=True)
class MoveLoggedEvent:
    """Raw facts about an accepted move/jump - GameEngine.request_move/
    request_jump's entire contribution to the moves log. It deliberately
    carries no display text: turning these facts into notation (e.g. "Nf3",
    "exd5", "Nb1^") is boardio.algebraic_notation's job, invoked only by
    view/observers.py's MoveLogObserver - GameEngine (business/game-rule
    logic) has no business knowing that "notation" or a "moves log" exist
    at all, only that something worth reporting happened.

    A jump has no destination (see realtime.real_time_arbiter's
    start_jump) - destination is set equal to source for a jump, so this
    stays a single uniform shape instead of an Optional field only one of
    the two call sites ever leaves unset.
    """

    color: str
    kind: str
    source: Position
    destination: Position
    is_capture: bool
    is_jump: bool
    elapsed_ms: int


# A GameEngine notifies every registered GameObserver of these two hooks -
# a piece's move/jump being *accepted* (on_move_logged), and a motion's
# arrival being resolved (on_arrival, reusing ArrivalEvent so score-keeping
# always reflects what actually happened on the board, not what looked
# likely to happen when the request was made). Both are no-ops by default
# so a concrete observer (view/observers.py) only overrides the hook(s) it
# actually cares about, instead of implementing a full interface for events
# it ignores.
#
# This exists so GameEngine's move/jump pipeline never has to know that a
# moves log or a scoreboard exist at all - it just notifies whoever is
# listening and moves on, matching the "observer watches at its own pace,
# the core loop doesn't wait on it" design this was built for.
class GameObserver:
    def on_move_logged(self, event: MoveLoggedEvent) -> None:
        pass

    def on_arrival(self, event: ArrivalEvent) -> None:
        pass


@dataclass
class PieceSnapshot:
    id: str
    kind: str
    color: str
    # Continuous board coordinates, not pixels - the model has no notion of
    # screen space. A stationary piece sits at integer (row, col); a piece
    # mid-motion is fractional, interpolated between source and destination.
    # Converting these to pixels (multiplying by CELL_SIZE) is the view
    # layer's job (see view/renderer.py), never the engine's.
    row: float
    col: float
    state: str


@dataclass
class GameSnapshot:
    board_width: int
    board_height: int
    pieces: List[PieceSnapshot]
    selected_cell: Optional[Position]
    game_over: bool
