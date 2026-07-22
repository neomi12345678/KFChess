"""Wire vocabulary shared by *both* sides of the network connection: the
server-endpoint address, the color-letter mapping, and the JSON shapes for
a broadcast snapshot and its side-panel data. Lives at the top level,
outside server/, because a client has no business importing the server
package just to talk the server's own wire format - client/client_cli.py,
client/game_view_state.py, and play_online.py all import from here instead
of from server.protocol.

server/protocol.py builds its server-only half (text command grammar:
parsing "We2e4"/"LOGIN ..."/"PLAY"/room commands) on top of this - nothing
in server/protocol.py duplicates what's here, it only imports COLOR_PREFIX
back for its own parsing.

The grammar's *building* half (build_login/build_play/build_create_room/
build_cancel_room/build_join_room/build_move/build_jump, below) lives here
too, not in server/protocol.py - a client only ever builds a command, never
parses one back apart, so it has no reason to import the server package for
this either. Every command-sending call site (client/client_cli.py,
client/network_client.py, play_online.py) uses these instead of each
hand-rolling its own copy of the same literal wire text.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from events.observers import MoveLogObserver, ScoreObserver
from model.game_state import GameSnapshot, PieceSnapshot
from model.piece import BLACK, WHITE
from model.position import Position

# The real, well-known server endpoint - a single source both
# server/main.py (binding) and every connecting client (client_cli.py,
# play_online.py) read from, instead of each hand-rolling its own copy.
HOST = "localhost"
PORT = 8765

# The wire format's own color letters - public so a client building a
# command (client/client_cli.py, play_online.py) can get "W"/"B" for its
# own seat from the same single source of truth server/protocol.py's
# parse_command parses commands back out of, instead of each hand-rolling
# its own copy of this mapping.
COLOR_PREFIX = {WHITE: "W", BLACK: "B"}


def build_login(username: str, password: str) -> str:
    return f"LOGIN {username} {password}"


def build_play() -> str:
    return "PLAY"


def build_create_room() -> str:
    return "CREATE_ROOM"


def build_cancel_room() -> str:
    return "CANCEL_ROOM"


def build_join_room(room_id: str) -> str:
    return f"JOIN_ROOM {room_id}"


def build_move(color: str, source: str, destination: str) -> str:
    return f"{COLOR_PREFIX[color]}{source}{destination}"


def build_jump(color: str, square: str) -> str:
    return f"{COLOR_PREFIX[color]}J{square}"


# Wire message "type" values - the vocabulary server/ws_server.py,
# server/game_loop.py, and server/session.py send, and client/network_client.py,
# client/client_cli.py, client/network_message_adapter.py match against.
# Centralized so a typo on either side of the connection is a NameError at
# import time instead of a message that silently never matches anything at
# runtime.
LOGIN_ACK = "login_ack"
PLAY_ACK = "play_ack"
CREATE_ROOM_ACK = "create_room_ack"
JOIN_ROOM_ACK = "join_room_ack"
CANCEL_ROOM_ACK = "cancel_room_ack"
SEAT = "seat"
ACK = "ack"
ERROR = "error"
GAME_OVER = "game_over"
DISCONNECT_COUNTDOWN = "disconnect_countdown"
MATCHMAKING_TIMEOUT = "matchmaking_timeout"
MOVE_LOGGED = "move_logged"
CAPTURE = "capture"


# One dataclass per server->client control message (everything except the
# per-tick snapshot broadcast, which stays a plain dict built by
# snapshot_to_json/panel_to_json below - it has no "type" of its own, see
# client/game_view_state.py's own "pieces" in message check). Each mirrors
# its message's exact real-world shape: a field is only Optional/defaulted
# if that message genuinely sends it sometimes and omits it other times
# (see server/connections.py's ConnectionRegistry.send, which drops None
# fields before serializing so the wire shape is unchanged from before
# these existed) - a field with no default is one every send site actually
# provides. Building one of these with a missing required field or a typo'd
# keyword argument is a TypeError at the send site, not a message a client
# silently never matches anything in.
@dataclass(frozen=True)
class ErrorMessage:
    message: str
    type: str = ERROR


@dataclass(frozen=True)
class LoginAckMessage:
    accepted: bool
    reason: Optional[str] = None
    username: Optional[str] = None
    rating: Optional[int] = None
    reconnected: Optional[bool] = None
    color: Optional[str] = None
    resuming_room_id: Optional[str] = None
    type: str = LOGIN_ACK


@dataclass(frozen=True)
class PlayAckMessage:
    accepted: bool
    reason: str
    type: str = PLAY_ACK


@dataclass(frozen=True)
class CreateRoomAckMessage:
    accepted: bool
    reason: Optional[str] = None
    room_id: Optional[str] = None
    type: str = CREATE_ROOM_ACK


@dataclass(frozen=True)
class JoinRoomAckMessage:
    accepted: bool
    reason: Optional[str] = None
    room_id: Optional[str] = None
    role: Optional[str] = None
    type: str = JOIN_ROOM_ACK


@dataclass(frozen=True)
class CancelRoomAckMessage:
    accepted: bool
    reason: Optional[str] = None
    type: str = CANCEL_ROOM_ACK


@dataclass(frozen=True)
class AckMessage:
    accepted: bool
    reason: str
    type: str = ACK


@dataclass(frozen=True)
class SeatMessage:
    color: str
    type: str = SEAT


@dataclass(frozen=True)
class MatchmakingTimeoutMessage:
    type: str = MATCHMAKING_TIMEOUT


@dataclass(frozen=True)
class DisconnectCountdownMessage:
    seat: str
    seconds_remaining: int
    type: str = DISCONNECT_COUNTDOWN


@dataclass(frozen=True)
class GameOverMessage:
    ratings: Dict[str, int]
    type: str = GAME_OVER


@dataclass(frozen=True)
class MoveLoggedMessage:
    is_jump: bool
    type: str = MOVE_LOGGED


@dataclass(frozen=True)
class CaptureMessage:
    type: str = CAPTURE


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
                "cooldown_remaining_ms": piece.cooldown_remaining_ms,
                "cooldown_total_ms": piece.cooldown_total_ms,
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
                cooldown_remaining_ms=piece["cooldown_remaining_ms"],
                cooldown_total_ms=piece["cooldown_total_ms"],
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
# server-side), so this never needs boardio's own notation grammar.
#
# names is the real {color: username} pair a GameSession already knows (see
# server/session.py's username_for) - optional (and defaulting to {}, not
# omitted from the payload) so callers that broadcast panel data without a
# real session at hand (there are none today, but nothing here assumes
# there never will be) still get a JSON-stable "names" key rather than one
# the client has to branch on the presence of. An absent color in the
# reconstructed dict (see PanelState.name_for) is what tells view/renderer.py
# not to draw a name line at all, rather than a placeholder string.
def panel_to_json(move_log: MoveLogObserver, score: ScoreObserver, names: Optional[Dict[str, str]] = None) -> dict:
    return {
        "move_log": {
            color: [{"notation": entry.notation, "elapsed_ms": entry.elapsed_ms} for entry in move_log.entries_for(color)]
            for color in (WHITE, BLACK)
        },
        "score": {color: score.score_for(color) for color in (WHITE, BLACK)},
        "names": dict(names) if names else {},
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
        self._name_by_color: dict = {}

    def update_from_json(self, payload: dict) -> None:
        self._entries_by_color = {
            color: [_PanelMoveLine(notation=entry["notation"], elapsed_ms=entry["elapsed_ms"]) for entry in entries]
            for color, entries in payload["move_log"].items()
        }
        self._score_by_color = payload["score"]
        # .get, not a bare payload["names"] - payload may be an older/other
        # caller's panel_to_json() dict (or a hand-built test fixture, see
        # tests/unit/test_server_protocol.py) from before "names" existed.
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
