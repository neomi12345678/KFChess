"""JSON codec for the per-tick broadcast: the full-board snapshot
(snapshot_to_json/snapshot_from_json) and the side-panel move-log/score/
names data merged into the same broadcast (panel_to_json) - see
panel_state.py's PanelState for the client-side read model rebuilt from
panel_to_json's own payload shape.

Neither the snapshot nor the panel data get a types.py "type" tag or a
registry.py registration - unlike every message in lobby_messages.py/
game_messages.py, the per-tick broadcast is the server's whole
authoritative state as of this tick, not a discrete, typed event. See
is_snapshot_payload below for the one shared predicate that tells a
snapshot broadcast apart from a typed message by shape - client/
network_client.py's decode_incoming is the one caller (both it and
client/client_cli.py, which shares that same decode_incoming rather than
hand-rolling its own check, end up relying on it).

position_to_json/position_from_json are also reused by game_messages.py's
MoveMessage/JumpMessage, the one piece of this codec that isn't specific to
the snapshot broadcast - a Position is a Position on the wire either way.
"""

from typing import Dict, Optional

from events.observers import MoveLogObserver, ScoreObserver
from model.game_state import GameSnapshot, PieceSnapshot
from model.piece import BLACK, WHITE
from model.position import Position


# "pieces" is the one key only a snapshot broadcast ever carries (see
# snapshot_to_json below) - the single predicate both client/network_client.py
# and client/client_cli.py use to tell a snapshot apart from a typed message,
# instead of each hand-rolling its own shape check (they used to check
# different keys - "pieces" vs "board_height" - which could silently drift
# apart if the wire shape ever changed).
def is_snapshot_payload(payload: dict) -> bool:
    return "pieces" in payload


def position_to_json(position: Optional[Position]) -> Optional[dict]:
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
        "selected_cell": position_to_json(snapshot.selected_cell),
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


def position_from_json(payload: Optional[dict]) -> Optional[Position]:
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
        selected_cell=position_from_json(payload["selected_cell"]),
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
