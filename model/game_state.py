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
    # False for a capture resolved while `piece` itself is still mid-flight
    # (see RealTimeArbiter._capture_blocked_mover and the opposite-color
    # branch of _intercept_motion): whoever had right of way keeps flying
    # toward its own original destination instead of stopping at the
    # collision, so `piece.cell`/`piece.state` at the moment of this event
    # do not yet reflect where it actually ends up - a later ArrivalEvent
    # for the same piece, with has_landed True, reports that once it's
    # actually known. True for every other capture/arrival, where `piece`
    # really has just settled at its current cell.
    has_landed: bool = True


@dataclass(frozen=True)
class MoveLoggedEvent:
    """Raw facts about an accepted move/jump - GameEngine.request_move/
    request_jump's entire contribution to the moves log. It deliberately
    carries no display text: turning these facts into notation (e.g. "Nf3",
    "exd5", "Nb1^") is boardio.algebraic_notation's job, invoked only by
    events/observers.py's MoveLogObserver - GameEngine (business/game-rule
    logic) has no business knowing that "notation" or a "moves log" exist
    at all, only that something worth reporting happened.

    A jump has no destination (see realtime.real_time_arbiter's
    start_jump) - destination is set equal to source for a jump, so this
    stays a single uniform shape instead of an Optional field only one of
    the two call sites ever leaves unset.

    destination/is_capture are only a request-time guess for a move (never
    for a jump, which is already final the instant it's requested) - a
    route conflict or a mid-flight interception (see RealTimeArbiter's
    plan_route/_intercept_motion) can still shorten where the piece actually
    lands or turn a quiet move into a capture. piece_id is carried only so
    a later ArrivalEvent for the same identity can be matched back to
    correct that guess (see events/observers.py's MoveLogObserver) - a raw
    identity fact, not a notation concept, so this stays true to this
    event's own "no display text" rule above.
    """

    color: str
    kind: str
    source: Position
    destination: Position
    is_capture: bool
    is_jump: bool
    elapsed_ms: int
    piece_id: str


# A GameEngine notifies every registered GameObserver of these two hooks -
# a piece's move/jump being *accepted* (on_move_logged), and a motion's
# arrival being resolved (on_arrival, reusing ArrivalEvent so score-keeping
# always reflects what actually happened on the board, not what looked
# likely to happen when the request was made). Both are no-ops by default
# so a concrete observer (events/observers.py) only overrides the hook(s) it
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
# consumer (view/canvas/sprite_frames.py's SpriteAnimator) can track how
# long *this* piece has been showing its current sprite across frames -
# GameEngine reports *which* phase a piece is in (including long_rest/
# short_rest, see motion_phase below) but never how long its sprite has
# been playing, so the view has to correlate frames by identity instead.
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
    # one of model.piece.PHASE_IDLE/PHASE_MOVE/PHASE_JUMP/PHASE_SHORT_REST/
    # PHASE_LONG_REST (see GameEngine._motion_phase). Resting is a real
    # game-state fact here, not a rendering invention - a piece on cooldown
    # is blocked from a new move/jump the same way a moving/airborne piece
    # is (see RealTimeArbiter.is_in_cooldown()). Named motion_phase, not
    # "animation", so this DTO reads as a game-state fact rather than a
    # rendering instruction - the model has no notion that "animation" is a
    # thing; which sprite folder each phase maps to is view/
    # animation_states.py's business alone.
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
