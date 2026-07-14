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
IDLE = "idle"
MOVING = "moving"
CAPTURED = "captured"
AIRBORNE = "airborne"
# Recovery periods after finishing an action, before the piece can act
# again - after an ordinary move (SHORT_REST is after a jump instead). Both
# mirror the animation state machine assets/pieces/*/states/*/config.json
# describes (move -> long_rest -> idle, jump -> short_rest -> idle).
SHORT_REST = "short_rest"
LONG_REST = "long_rest"

# Model state -> assets/pieces/<code>/states/<folder> animation folder name.
# The single source of truth for this mapping - graphics/animation.py reads
# it to pick sprites, realtime/real_time_arbiter.py reads it to look up a
# finishing state's own next_state_when_finished - so the two layers can
# never drift into disagreeing about what a state is called on disk.
# CAPTURED has no entry: a captured piece is off the board, never drawn or
# timed, so it never needs a folder.
STATE_FOLDER = {
    IDLE: "idle",
    MOVING: "move",
    AIRBORNE: "jump",
    SHORT_REST: "short_rest",
    LONG_REST: "long_rest",
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


# The state machine's "entry" half - from each real-time state, whether a
# "move" or "jump" may be *started*, and the reason to report back when it
# can't. GameEngine and RealTimeArbiter both consult this one table instead
# of each re-deriving their own piece.state checks, so there is exactly one
# place that says what a piece may do from a given state.
#
# The "exit" half - what state automatically follows once a timed state's
# own animation cycle finishes - is declared per piece in
# assets/pieces/<code>/states/<state>/config.json's next_state_when_finished
# and read by realtime/real_time_arbiter.py's _enter_state. Together the two
# halves are the full state graph: this table's entries only ever route
# through IDLE (both actions require it), and the JSON's exits only ever
# land back on IDLE, short_rest, or long_rest - so the two halves meet
# exactly at IDLE with no gap and no overlap.
_MOVE_AVAILABILITY = {
    IDLE: ActionAvailability(allowed=True),
    MOVING: ActionAvailability(allowed=False, reason_if_blocked="motion_in_progress"),
    AIRBORNE: ActionAvailability(allowed=False, reason_if_blocked="piece_is_airborne"),
    SHORT_REST: ActionAvailability(allowed=False, reason_if_blocked="piece_in_cooldown"),
    LONG_REST: ActionAvailability(allowed=False, reason_if_blocked="piece_in_cooldown"),
    CAPTURED: ActionAvailability(allowed=False, reason_if_blocked="piece_in_cooldown"),
}

_JUMP_AVAILABILITY = {
    IDLE: ActionAvailability(allowed=True),
    MOVING: ActionAvailability(allowed=False, reason_if_blocked="piece_is_moving"),
    AIRBORNE: ActionAvailability(allowed=False, reason_if_blocked="piece_is_moving"),
    SHORT_REST: ActionAvailability(allowed=False, reason_if_blocked="piece_in_cooldown"),
    LONG_REST: ActionAvailability(allowed=False, reason_if_blocked="piece_in_cooldown"),
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
