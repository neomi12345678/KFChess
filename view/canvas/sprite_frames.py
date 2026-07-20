import time

import piece_config
from view.animation_states import STATE_FOLDER
from view.piece_state_machine import PieceAnimationStateMachine

# A piece not covered by view.animation_states.STATE_FOLDER (captured, or a
# future addition) falls back to "idle" - a piece that isn't one of
# GameEngine's reported real-time phases shouldn't be on the board to draw
# in the first place.


class SpriteAnimator:
    """Picks which sprite frame to show for a piece, driven by each
    animation folder's own config.json (frames_per_sec/is_loop, read via
    piece_config.py). How long a piece has continuously been in its current
    folder is view/piece_state_machine.py's PieceAnimationStateMachine's job
    (self._state_machine below) - this class only ever turns that elapsed
    time into a frame index, never tracks state itself. Real move/jump/
    short_rest/long_rest timing all come from logic_config.py's fixed
    duration constants instead - none of it depends on this class's frame
    count/frames_per_sec, which only ever affect which sprite gets
    painted, never how long a state lasts.
    """

    # clock is injectable so tests can control elapsed time deterministically
    # instead of sleeping in real time. skin defaults to DEFAULT_SKIN, same
    # reasoning as every other cell_size-style constructor argument in
    # view/ - a caller that wants a different skin passes a different
    # piece_config.Skin in, everyone else is unaffected.
    def __init__(self, clock=time.monotonic, skin: piece_config.Skin = piece_config.DEFAULT_SKIN):
        self._skin = skin
        self._state_machine = PieceAnimationStateMachine(clock=clock)

    def sprite_path(self, piece_id: str, piece_code: str, state: str):
        folder = STATE_FOLDER.get(state, "idle")
        elapsed_s = self._state_machine.enter(piece_id, folder)
        frame = self._frame_for(piece_code, folder, elapsed_s)
        return self._skin.pieces_dir / piece_code / "states" / folder / "sprites" / f"{frame}.png"

    # Forgets any piece_id not in `present_piece_ids` - see
    # PieceAnimationStateMachine.forget_missing. Called once per rendered
    # frame (see view/canvas/img_canvas.py's ImgCanvas.begin_frame) with
    # every piece_id actually drawn the frame before, so a captured piece's
    # animation clock doesn't linger forever.
    def forget_missing(self, present_piece_ids) -> None:
        self._state_machine.forget_missing(present_piece_ids)

    def _frame_for(self, piece_code: str, folder: str, elapsed_s: float) -> int:
        state_config = piece_config.load_animation(piece_code, folder, self._skin)

        elapsed_frames = int(elapsed_s * state_config.frames_per_sec)
        if state_config.is_loop:
            index = elapsed_frames % state_config.frame_count
        else:
            index = min(elapsed_frames, state_config.frame_count - 1)
        return index + 1  # sprite files are 1-indexed
