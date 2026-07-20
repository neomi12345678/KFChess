"""Wire protocol for the networked server: text commands in, JSON snapshots
out. Kept fully isolated from boardio/ - this is a network-facing vocabulary
(uppercase "W"/"B" color letters, no piece letter, a bare "J" jump marker)
distinct from boardio's own board-notation/algebraic-notation letters, so it
has no business living alongside those.

Command grammar:
    "<W|B><source><dest>"   e.g. "We2e4" - move
    "<W|B>J<square>"        e.g. "WJe4"  - jump (in place, no destination)
    "LOGIN <username> <password>"  e.g. "LOGIN alice secret123" - the
                            connection's login step (see
                            server/ws_server.py and server/accounts.py),
                            space-delimited rather than this file's compact
                            move/jump grammar since a username/password are
                            free text, not fixed-width squares.
    "PLAY"                  requests matchmaking (see server/matchmaking.py)
                            - no arguments, since the connection's own
                            identity/rating are already known from LOGIN.
where <square> is a file letter ("a".."h"-range, board-width-dependent) plus
a rank number, the same square-name shape as boardio.algebraic_notation's
square_name, just inverted.
"""

from dataclasses import dataclass
from typing import List, Optional

from events.observers import MoveLogObserver, ScoreObserver
from model.game_state import GameSnapshot, PieceSnapshot
from model.piece import BLACK, WHITE
from model.position import Position

_COLOR_BY_PREFIX = {"W": WHITE, "B": BLACK}
_LOGIN_PREFIX = "LOGIN "
PLAY_COMMAND = "PLAY"

MOVE = "move"
JUMP = "jump"


class ProtocolError(Exception):
    """A command string that doesn't match the grammar at all, or names a
    square outside the board - never raised for a legal-looking command
    that GameEngine itself goes on to reject (route conflict, cooldown,
    wrong color, ...); those are reported back as an ordinary rejection,
    not a protocol failure."""


@dataclass(frozen=True)
class Command:
    color: str
    kind: str
    source: Position
    destination: Optional[Position]


# The inverse of boardio.algebraic_notation.square_name: file letter -> col,
# rank number -> row, using the same board_height-relative convention (row 0
# is rank board_height, matching white's pawns advancing toward row 0).
def parse_square(square: str, board_height: int) -> Position:
    if len(square) < 2 or not square[0].isalpha() or not square[1:].isdigit():
        raise ProtocolError(f"malformed square: '{square}'")

    col = ord(square[0].lower()) - ord("a")
    rank_number = int(square[1:])
    row = board_height - rank_number

    if col < 0:
        raise ProtocolError(f"malformed square: '{square}'")

    return Position(row, col)


def parse_command(text: str, board_height: int) -> Command:
    if len(text) < 2 or text[0] not in _COLOR_BY_PREFIX:
        raise ProtocolError(f"malformed command: '{text}'")

    color = _COLOR_BY_PREFIX[text[0]]
    rest = text[1:]

    if rest[0] == "J":
        return Command(color=color, kind=JUMP, source=parse_square(rest[1:], board_height), destination=None)

    # A move's source/dest are both fixed-width squares (one file letter,
    # then digits) with no separator, so the split point is wherever the
    # rank digits of the first square end and the second square's file
    # letter begins.
    split = 1
    while split < len(rest) and rest[split].isdigit():
        split += 1
    if split >= len(rest):
        raise ProtocolError(f"malformed command: '{text}'")

    source = parse_square(rest[:split], board_height)
    destination = parse_square(rest[split:], board_height)
    return Command(color=color, kind=MOVE, source=source, destination=destination)


@dataclass(frozen=True)
class LoginRequest:
    username: str
    password: str


# Returns the (username, password) for a "LOGIN <username> <password>"
# message, or None for any other text - lets a caller (server/ws_server.py)
# check "was this a login message at all?" without first needing to know it
# wasn't a move/jump. Still raises ProtocolError for a recognized-but-
# malformed login (missing username or password), the same way
# parse_command raises for a recognized-but-malformed move/jump, rather than
# silently treating it as "not a login message". The password itself is
# whatever text follows the username, spaces included - only the boundary
# between username and password is split on the first run of whitespace.
def parse_login(text: str) -> Optional[LoginRequest]:
    if not text.startswith(_LOGIN_PREFIX):
        return None

    rest = text[len(_LOGIN_PREFIX):].strip()
    parts = rest.split(None, 1)
    if len(parts) != 2 or not parts[1].strip():
        raise ProtocolError("LOGIN requires a username and a password")

    return LoginRequest(username=parts[0], password=parts[1].strip())


def is_play_command(text: str) -> bool:
    return text.strip() == PLAY_COMMAND


def _position_to_json(position: Optional[Position]) -> Optional[dict]:
    if position is None:
        return None
    return {"row": position.row, "col": position.col}


# Plain-dict form of GameSnapshot, JSON-serializable as-is - dataclasses.asdict
# would work too, but this is explicit about the exact wire shape rather than
# mirroring GameSnapshot's Python-side field layout by accident.
def snapshot_to_json(snapshot) -> dict:
    return {
        "board_width": snapshot.board_width,
        "board_height": snapshot.board_height,
        "game_over": snapshot.game_over,
        "selected_cell": _position_to_json(snapshot.selected_cell),
        "pieces": [
            {
                "id": piece.id,
                "kind": piece.kind,
                "color": piece.color,
                "row": piece.row,
                "col": piece.col,
                "state": piece.state,
                "motion_phase": piece.motion_phase,
            }
            for piece in snapshot.pieces
        ],
    }


def _position_from_json(payload: Optional[dict]) -> Optional[Position]:
    if payload is None:
        return None
    return Position(payload["row"], payload["col"])


# The inverse of snapshot_to_json - lets a networked GUI client (see
# play_online.py) render a broadcast the same way view/renderer.py already
# renders a local GameSnapshot, without that module needing to know it came
# over a wire instead of straight from engine/game_engine.py.
def snapshot_from_json(payload: dict) -> GameSnapshot:
    return GameSnapshot(
        board_width=payload["board_width"],
        board_height=payload["board_height"],
        game_over=payload["game_over"],
        selected_cell=_position_from_json(payload["selected_cell"]),
        pieces=tuple(
            PieceSnapshot(
                id=piece["id"],
                kind=piece["kind"],
                color=piece["color"],
                row=piece["row"],
                col=piece["col"],
                state=piece["state"],
                motion_phase=piece["motion_phase"],
            )
            for piece in payload["pieces"]
        ),
    )


# Per-color moves-log/score panel data (see view/renderer.py's own side
# panels) - kept as its own dict, merged into the same broadcast as
# snapshot_to_json's board state rather than added as GameSnapshot fields:
# GameEngine itself never produces a moves log or a score at all (see
# events/observers.py's own docstring), only whichever caller registered
# these two observers on it does - here, server/session.py's GameSession.
# entry.notation is already resolved display text by the time this runs
# (events.observers.MoveLogObserver did that conversion synchronously,
# server-side), so this never needs boardio's own notation grammar - the
# isolation this module's docstring promises stays intact.
def panel_to_json(move_log: MoveLogObserver, score: ScoreObserver) -> dict:
    return {
        "move_log": {
            color: [{"notation": entry.notation, "elapsed_ms": entry.elapsed_ms} for entry in move_log.entries_for(color)]
            for color in (WHITE, BLACK)
        },
        "score": {color: score.score_for(color) for color in (WHITE, BLACK)},
    }


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

    def update_from_json(self, payload: dict) -> None:
        self._entries_by_color = {
            color: [_PanelMoveLine(notation=entry["notation"], elapsed_ms=entry["elapsed_ms"]) for entry in entries]
            for color, entries in payload["move_log"].items()
        }
        self._score_by_color = payload["score"]

    def entries_for(self, color: str) -> List[_PanelMoveLine]:
        return self._entries_by_color.get(color, [])

    def score_for(self, color: str) -> int:
        return self._score_by_color.get(color, 0)
