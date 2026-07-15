import time
from dataclasses import dataclass

import piece_config
from view.animation_states import STATE_FOLDER

# A piece not covered by view.animation_states.STATE_FOLDER (captured, or a
# future addition) falls back to "idle" - a piece that isn't one of the
# mapped real-time states shouldn't be on the board to draw in the first
# place.


@dataclass
class _EnteredState:
    folder: str
    entered_at: float


class SpriteAnimator:
    """Picks which sprite frame to show for a piece, driven by each
    animation folder's own config.json (frames_per_sec/is_loop, read via
    piece_config.py) - the same state machine the course's config format
    describes, just read for its graphics half only. Real move timing
    comes from physics/motion.py's speed_m_per_sec; jump/short_rest/
    long_rest timing comes from config.py's fixed base-duration constants -
    neither depends on this class's frame count/frames_per_sec, which only
    ever affect which sprite gets painted, never how long a state lasts.
    """

    # clock is injectable so tests can control elapsed time deterministically
    # instead of sleeping in real time.
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._entered_by_piece_id: dict[str, _EnteredState] = {}

    def sprite_path(self, piece_id: str, piece_code: str, state: str):
        folder = STATE_FOLDER.get(state, "idle")
        frame = self._current_frame(piece_id, piece_code, folder)
        return piece_config.PIECES_DIR / piece_code / "states" / folder / "sprites" / f"{frame}.png"

    def _current_frame(self, piece_id: str, piece_code: str, folder: str) -> int:
        now = self._clock()
        entered = self._entered_by_piece_id.get(piece_id)
        if entered is None or entered.folder != folder:
            entered = _EnteredState(folder=folder, entered_at=now)
            self._entered_by_piece_id[piece_id] = entered

        state_config = piece_config.load(piece_code, folder)

        elapsed_frames = int((now - entered.entered_at) * state_config.frames_per_sec)
        if state_config.is_loop:
            index = elapsed_frames % state_config.frame_count
        else:
            index = min(elapsed_frames, state_config.frame_count - 1)
        return index + 1  # sprite files are 1-indexed
