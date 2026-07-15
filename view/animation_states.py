"""Presentation-only animation-state vocabulary.

GameEngine.snapshot() only ever reports model.piece.PHASE_IDLE/PHASE_MOVE/
PHASE_JUMP - a piece being in a post-move/post-jump cooldown is never part
of that report (see RealTimeArbiter.is_in_cooldown(), tracked out-of-band
from anything the engine exposes). SHORT_REST/LONG_REST below are a purely
cosmetic overlay view/piece_state_machine.py layers on top of the engine's
report for display, and STATE_FOLDER is the asset-folder-name mapping only
the view/graphics side needs - none of this has any bearing on game state,
so none of it lives in model/piece.py.
"""

from model.piece import PHASE_IDLE, PHASE_JUMP, PHASE_MOVE

SHORT_REST = "short_rest"
LONG_REST = "long_rest"

# Animation state -> assets/pieces/<code>/states/<folder> animation folder
# name. The single source of truth for this mapping - graphics/animation.py
# and view/piece_state_machine.py both read it, so the two can never drift
# into disagreeing about what an animation state is called on disk.
STATE_FOLDER = {
    PHASE_IDLE: "idle",
    PHASE_MOVE: "move",
    PHASE_JUMP: "jump",
    SHORT_REST: "short_rest",
    LONG_REST: "long_rest",
}
