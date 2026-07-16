"""Presentation-only asset-folder-name mapping.

GameEngine.snapshot() reports whichever of model.piece.PHASE_IDLE/
PHASE_MOVE/PHASE_JUMP/PHASE_SHORT_REST/PHASE_LONG_REST a piece is
currently in (see RealTimeArbiter.is_in_short_rest()/is_in_long_rest()) -
resting is a real game-state fact, not something this module invents.
STATE_FOLDER below is the one thing that *is* view-only: which
assets/pieces/<code>/states/<folder> directory each phase's sprites live
in.
"""

from model.piece import PHASE_IDLE, PHASE_JUMP, PHASE_LONG_REST, PHASE_MOVE, PHASE_SHORT_REST

# Real-time phase -> assets/pieces/<code>/states/<folder> animation folder
# name. The single source of truth for this mapping - view/canvas/
# sprite_frames.py is the only reader.
STATE_FOLDER = {
    PHASE_IDLE: "idle",
    PHASE_MOVE: "move",
    PHASE_JUMP: "jump",
    PHASE_SHORT_REST: "short_rest",
    PHASE_LONG_REST: "long_rest",
}
