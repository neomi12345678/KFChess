from dataclasses import dataclass
from typing import Optional, Protocol

from model.position import Position

# Semantic values, not board-notation letters - keeps rules/engine/arbiter
# code free of the "w"/"K" text tokens used only for parsing and printing.
WHITE = "white"
BLACK = "black"

KING = "king"
QUEEN = "queen"
ROOK = "rook"
BISHOP = "bishop"
KNIGHT = "knight"
PAWN = "pawn"

# A piece's real-time lifecycle state, independent of its board position.
# Deliberately just these three: whether a piece is currently airborne
# (mid-jump) or resting (post-move/post-jump cooldown) is never encoded
# here - those are realtime.real_time_arbiter.RealTimeArbiter's own
# out-of-band bookkeeping (is_airborne()/is_in_cooldown()), tracked
# per-piece-id independently of this field, so a captured/resurrected
# identity mixup can never leave a piece stuck mid-air or mid-rest by
# mistake. See ANIMATION_* below for the separate, purely cosmetic
# vocabulary a renderer uses instead.
IDLE = "idle"
MOVING = "moving"
CAPTURED = "captured"

# What a renderer should currently be playing - a piece's own state above
# never takes these values. GameEngine.snapshot() only ever reports
# ANIMATION_IDLE/ANIMATION_MOVE/ANIMATION_JUMP (see RealTimeArbiter.
# is_airborne()); ANIMATION_LONG_REST/ANIMATION_SHORT_REST are only ever
# produced by view/piece_state_machine.py, layered on top for display -
# the engine itself has no notion that a "rest animation" exists.
ANIMATION_IDLE = "idle"
ANIMATION_MOVE = "move"
ANIMATION_JUMP = "jump"
ANIMATION_SHORT_REST = "short_rest"
ANIMATION_LONG_REST = "long_rest"

# Animation state -> assets/pieces/<code>/states/<folder> animation folder
# name. The single source of truth for this mapping - graphics/animation.py
# and view/piece_state_machine.py both read it, so the two can never drift
# into disagreeing about what an animation state is called on disk.
STATE_FOLDER = {
    ANIMATION_IDLE: "idle",
    ANIMATION_MOVE: "move",
    ANIMATION_JUMP: "jump",
    ANIMATION_SHORT_REST: "short_rest",
    ANIMATION_LONG_REST: "long_rest",
}


class PieceRepresentation(Protocol):
    """The state contract every piece implementation must satisfy.

    Rules, the engine, the arbiter, and realtime motion tracking depend
    only on these members, never on Piece's concrete dataclass layout -
    so a future binary/packed representation can be dropped in,
    implementing just this shape, without touching a single line of game
    logic.
    """

    id: str
    color: str
    kind: str
    cell: Position
    state: str


@dataclass
class Piece:
    id: str
    color: str
    kind: str
    cell: Position
    state: str = IDLE


@dataclass(frozen=True)
class ActionAvailability:
    allowed: bool
    reason_if_blocked: Optional[str] = None


# From each of piece.state's three real values, whether a "move" or "jump"
# may be *started*, and the reason to report back when it can't. Whether a
# piece is airborne or resting is a separate, out-of-band question this
# table has no notion of at all - see RealTimeArbiter.is_airborne()/
# is_in_cooldown(), which GameEngine and RealTimeArbiter consult directly
# for those, alongside this table, before starting a new move/jump.
_MOVE_AVAILABILITY = {
    IDLE: ActionAvailability(allowed=True),
    MOVING: ActionAvailability(allowed=False, reason_if_blocked="motion_in_progress"),
    CAPTURED: ActionAvailability(allowed=False, reason_if_blocked="piece_in_cooldown"),
}

_JUMP_AVAILABILITY = {
    IDLE: ActionAvailability(allowed=True),
    MOVING: ActionAvailability(allowed=False, reason_if_blocked="piece_is_moving"),
    CAPTURED: ActionAvailability(allowed=False, reason_if_blocked="piece_in_cooldown"),
}


def move_availability(state: str) -> ActionAvailability:
    return _MOVE_AVAILABILITY[state]


def jump_availability(state: str) -> ActionAvailability:
    return _JUMP_AVAILABILITY[state]


# A piece mid-motion can't be (re)selected as a new move's source - its cell
# is already committed elsewhere. Resting/airborne pieces stay selectable:
# selecting one doesn't fail by itself, only a subsequent move/jump request
# against it does (see move_availability/jump_availability above).
def is_selectable(state: str) -> bool:
    return state != MOVING


# Single source of truth for board notation: which one-letter token stands
# for which color/kind. Adding a piece kind here is the only registration
# a custom board notation needs - boardio derives its valid-token set from
# these tables instead of hardcoding its own list.
COLOR_BY_LETTER = {"w": WHITE, "b": BLACK}
KIND_BY_LETTER = {"K": KING, "Q": QUEEN, "R": ROOK, "B": BISHOP, "N": KNIGHT, "P": PAWN}

# Standard chess piece values, used to turn a capture into a score delta
# (view/observers.py's ScoreObserver) - display-only, this has no bearing on
# game rules or the win condition. KING is 0 since capturing it already ends
# the game via KingCaptureWinCondition rather than merely scoring a point.
PIECE_VALUES = {PAWN: 1, KNIGHT: 3, BISHOP: 3, ROOK: 5, QUEEN: 9, KING: 0}
