from dataclasses import dataclass
from typing import Optional, Tuple

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


# Frozen: a read-only fact sheet for the view (see view/renderer.py), not a
# handle onto the real Piece - nothing downstream can mutate a field back
# into GameEngine's own state through this. id is still a plain str, not a
# reference to the real Piece object, kept only so a per-piece-id-keyed
# consumer (view/piece_state_machine.py's PieceStateMachine, graphics/
# animation.py's SpriteAnimator) can track how long *this* piece has been in
# its current visual state across frames - GameEngine itself never resolves
# that duration (it has no notion of long_rest/short_rest, see motion_phase
# below), so the view has to correlate frames by identity instead.
@dataclass(frozen=True)
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
    # The engine's own report of what real-time phase this piece is in -
    # always one of model.piece.PHASE_IDLE/PHASE_MOVE/PHASE_JUMP (see
    # GameEngine._animation_state). Never SHORT_REST/LONG_REST - those are a
    # purely cosmetic overlay only view/piece_state_machine.py ever
    # produces (see view/animation_states.py), layered on top of this
    # report for display, with no bearing on game state. Named
    # motion_phase, not "animation", so this DTO reads as a game-state fact
    # rather than a rendering instruction - the model has no notion that
    # "animation" is a thing.
    motion_phase: str


# Frozen for the same reason PieceSnapshot is - the view's own read-only copy
# of "what does the board look like right now", not a live handle onto
# GameEngine's state. pieces is a tuple, not a list, so the whole snapshot is
# actually immutable end to end (a frozen dataclass alone wouldn't stop a
# consumer from appending to a mutable list field).
@dataclass(frozen=True)
class GameSnapshot:
    board_width: int
    board_height: int
    pieces: Tuple[PieceSnapshot, ...]
    selected_cell: Optional[Position]
    game_over: bool
