from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol

from model.position import Position

# Semantic values, not board-notation letters - keeps rules/engine/arbiter
# code free of the "w"/"K" text tokens used only for parsing and printing.
# A str subclass, not a plain Enum, for the same reason ActionResultReason
# below is one: every existing `color == WHITE`-style comparison, dict-key
# lookup (COLOR_BY_LETTER, net_protocol.py's COLOR_PREFIX), and
# json.dumps(piece.color) call site keeps working unchanged, since a str
# Enum member compares equal to - and serializes as - its own string value.
# __str__ is overridden back to the plain value on purpose: Python 3.11+
# changed Enum.__format__ to render a mixed-in member as "Color.WHITE" in
# an f-string/str() instead of the mixin's own value (only ==/hash/
# json.dumps were left alone) - piece_config.py's piece_code and view/
# renderer.py's f-string draw-image key both interpolate color directly and
# need the plain "white"/"black" text, not the enum's repr.
class Color(str, Enum):
    WHITE = "white"
    BLACK = "black"

    def __str__(self) -> str:
        return self.value


# Back-compat aliases - every existing `model.piece.WHITE`/`from model.piece
# import WHITE, BLACK` call site (rules/, server/, client/, net_protocol.py,
# tests/) keeps working unchanged, now backed by a real enum member instead
# of a bare string.
WHITE = Color.WHITE
BLACK = Color.BLACK

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
# out-of-band bookkeeping (is_airborne()/is_in_short_rest()/
# is_in_long_rest()), tracked per-piece-id independently of this field, so
# a captured/resurrected identity mixup can never leave a piece stuck
# mid-air or mid-rest by mistake. See PHASE_* below for the real-time
# vocabulary GameEngine.snapshot() reports instead, built from that same
# out-of-band bookkeeping.
IDLE = "idle"
MOVING = "moving"
CAPTURED = "captured"

# What real-time phase GameEngine.snapshot() reports a piece is currently
# in (see RealTimeArbiter.is_airborne()/is_in_short_rest()/
# is_in_long_rest()) - a piece's own state above never takes these values.
# Resting gets its own two phases, not a collapse back to PHASE_IDLE: a
# piece on cooldown is blocked from starting a new move/jump exactly like a
# piece that's actually moving or airborne (see move_availability/
# jump_availability and RealTimeArbiter.is_in_cooldown()), so it's as much
# a real game-state fact as PHASE_MOVE/PHASE_JUMP are, not a rendering
# invention. Short vs. long only matters because a landed jump and a landed
# move earn different cooldown durations (see logic_config.py) - which
# *sprite* a renderer shows for either is still entirely view/
# animation_states.py's business, layered on top of this report.
PHASE_IDLE = "idle"
PHASE_MOVE = "move"
PHASE_JUMP = "jump"
PHASE_SHORT_REST = "short_rest"
PHASE_LONG_REST = "long_rest"


class PieceRepresentation(Protocol):
    """The state contract every piece implementation must satisfy.

    Rules, the engine, the arbiter, and realtime motion tracking depend
    only on these members, never on Piece's concrete dataclass layout -
    so a future binary/packed representation can be dropped in,
    implementing just this shape, without touching a single line of game
    logic.
    """

    id: str
    color: Color
    kind: str
    cell: Position
    state: str


@dataclass
class Piece:
    id: str
    color: Color
    kind: str
    cell: Position
    state: str = IDLE


# Every reason a move/jump request can be rejected for, across
# rules/board_rules.py, rules/rule_engine.py, engine/game_engine.py, and
# server/session.py - one shared, typed vocabulary instead of each layer
# inventing its own ad hoc string. A str subclass, not a plain Enum: every
# existing `result.reason == "route_conflict"`-style comparison (tests,
# server/ws_server.py's JSON replies) keeps working unchanged, since a str
# Enum member compares equal to - and json.dumps's as - its own string value.
class ActionResultReason(str, Enum):
    OK = "ok"
    GAME_OVER = "game_over"
    MOTION_IN_PROGRESS = "motion_in_progress"
    PIECE_IS_AIRBORNE = "piece_is_airborne"
    PIECE_IS_MOVING = "piece_is_moving"
    PIECE_IN_COOLDOWN = "piece_in_cooldown"
    ROUTE_CONFLICT = "route_conflict"
    EMPTY_CELL = "empty_cell"
    NOT_YOUR_PIECE = "not_your_piece"
    ILLEGAL_PIECE_MOVE = "illegal_piece_move"
    OUTSIDE_BOARD = "outside_board"
    EMPTY_SOURCE = "empty_source"
    FRIENDLY_DESTINATION = "friendly_destination"


@dataclass(frozen=True)
class ActionAvailability:
    allowed: bool
    reason_if_blocked: Optional[ActionResultReason] = None


# From each of piece.state's two *reachable* values, whether a "move" or
# "jump" may be *started*, and the reason to report back when it can't.
# CAPTURED is deliberately not a key here: a piece is always removed from
# the Board (see RealTimeArbiter._mark_captured's call sites) in the same
# operation that marks it CAPTURED, so GameEngine can never look one up via
# board.get_piece() and reach this table with it - a state.py Piece read
# straight off the board is always IDLE or MOVING. Whether a piece is
# airborne or resting is a separate, out-of-band question this table has no
# notion of at all - see RealTimeArbiter.is_airborne()/is_in_cooldown(),
# which GameEngine and RealTimeArbiter consult directly for those,
# alongside this table, before starting a new move/jump.
_MOVE_AVAILABILITY = {
    IDLE: ActionAvailability(allowed=True),
    MOVING: ActionAvailability(allowed=False, reason_if_blocked=ActionResultReason.MOTION_IN_PROGRESS),
}

_JUMP_AVAILABILITY = {
    IDLE: ActionAvailability(allowed=True),
    MOVING: ActionAvailability(allowed=False, reason_if_blocked=ActionResultReason.PIECE_IS_MOVING),
}


def move_availability(state: str) -> ActionAvailability:
    return _MOVE_AVAILABILITY[state]


def jump_availability(state: str) -> ActionAvailability:
    return _JUMP_AVAILABILITY[state]


# A piece mid-motion can't be (re)selected as a new move's source - its cell
# is already committed elsewhere. Resting/airborne pieces stay selectable:
# selecting one doesn't fail by itself, only a subsequent move/jump request
# against it does (see move_availability/jump_availability above). Checked
# against IDLE directly, not "!= MOVING" - a piece read straight off the
# board is always IDLE or MOVING (see _MOVE_AVAILABILITY's own comment on
# why CAPTURED never reaches here), so this stays correct even if some
# future caller passes CAPTURED in directly instead of through the board.
def is_selectable(state: str) -> bool:
    return state == IDLE


# Single source of truth for board notation: which one-letter token stands
# for which color/kind. Adding a piece kind here is the only registration
# a custom board notation needs - boardio derives its valid-token set from
# these tables instead of hardcoding its own list.
COLOR_BY_LETTER = {"w": WHITE, "b": BLACK}
KIND_BY_LETTER = {"K": KING, "Q": QUEEN, "R": ROOK, "B": BISHOP, "N": KNIGHT, "P": PAWN}

# Standard chess piece values, used to turn a capture into a score delta
# (events/observers.py's ScoreObserver) - display-only, this has no bearing on
# game rules or the win condition. KING is 0 since capturing it already ends
# the game via KingCaptureWinCondition rather than merely scoring a point.
PIECE_VALUES = {PAWN: 1, KNIGHT: 3, BISHOP: 3, ROOK: 5, QUEEN: 9, KING: 0}
