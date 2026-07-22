import pathlib

import cv2
import numpy as np

import piece_config
from display_config import CELL_SIZE
from view.canvas.img import Img
from view.canvas.sprite_frames import SpriteAnimator

_TEXT_FONT = cv2.FONT_HERSHEY_SIMPLEX

# draw_cooldown_bar's own sizing, as fractions of cell_size - a short bar,
# not the full width of the square, so it reads as a small clock/timer
# rather than another cell-wide highlight.
_COOLDOWN_BAR_LENGTH_FRAC = 0.5
_COOLDOWN_BAR_HEIGHT_FRAC = 0.1


class ImgCanvas:
    """Implements the draw_rect/draw_image/highlight_cell/draw_cooldown_bar/
    draw_text interface that view/renderer.py expects, using only
    view/canvas/img.py (Img) as the drawing backend. Lives under
    view/canvas/ rather than beside renderer.py itself because it's the
    concrete cv2-backed implementation of the canvas port Renderer only
    ever talks to through that abstract interface - renderer.py itself
    never imports this module, or cv2, at all.
    """

    # board.png's native resolution (828x822) doesn't divide evenly into
    # cell_size-sized cells - resizing it to exactly width*height cells here
    # is what keeps every piece aligned to its square instead of drifting.
    #
    # cell_size defaults to display_config's fixed CELL_SIZE but takes it as
    # a constructor argument - same reasoning as input.board_mapper.
    # BoardMapper's own cell_size - so play.py can thread through whatever
    # display_config.compute_cell_size decided for the actual screen at
    # launch, without this class reaching into that decision itself.
    #
    # side_panel_width_px reserves blank margins left and right of the board
    # for view/renderer.py's moves-log/score/name panels - 0 by default, so
    # any caller that doesn't ask for panels gets a frame sized exactly to
    # the board, byte-identical to before this existed. When it's set, the
    # board is inset by that many pixels on each side and every board-
    # relative draw call below (draw_image/highlight_cell) shifts by the
    # same amount; draw_text does not, since Renderer already computes
    # frame-absolute coordinates for anything it draws outside the board
    # (see view/renderer.py).
    #
    # skin defaults to piece_config.DEFAULT_SKIN (today's assets/board.png +
    # assets/pieces), same reasoning as cell_size above - a caller that
    # wants a different board/piece set passes a different piece_config.Skin
    # in, everyone else is unaffected.
    def __init__(
        self,
        board_width: int = 8,
        board_height: int = 8,
        side_panel_width_px: int = 0,
        cell_size: int = CELL_SIZE,
        skin: piece_config.Skin = piece_config.DEFAULT_SKIN,
    ):
        self._cell_size = cell_size
        # INTER_NEAREST, not Img.read's own INTER_AREA default - board.png is
        # a crisp checkerboard, not a photograph, and INTER_AREA's
        # area-weighted averaging still blends a stray pixel across each
        # square boundary even when the source edge itself is perfectly
        # hard (as it now is - see board.png's own generation). A highlighted
        # cell (see highlight_cell below) draws a mathematically exact
        # cell_size-aligned rectangle; this is what keeps the checker square
        # underneath it just as exact, instead of a soft blurred edge peeking
        # out from under a crisp highlight.
        self._board = Img().read(
            skin.board_path, size=(board_width * cell_size, board_height * cell_size), interpolation=cv2.INTER_NEAREST
        )
        self._board_offset_x = side_panel_width_px
        self._frame = None
        self._animator = SpriteAnimator(skin=skin)
        # Every piece_id drawn since the last begin_frame() - handed to the
        # animator's own forget_missing on the *next* begin_frame(), so a
        # captured piece's animation-state entry is pruned within one frame
        # of it no longer being drawn, instead of lingering for the rest of
        # the game.
        self._piece_ids_drawn: set[str] = set()
        # Every (piece_code, state, frame) sprite file's pixels never change
        # once loaded - reading + resizing it fresh from disk on every
        # draw_image call (every piece, every rendered frame) would be pure
        # waste, so cache the decoded Img by its resolved path. draw_on only
        # ever writes into the *target* frame, never mutates the sprite's
        # own pixels beyond a one-time channel-count conversion, so reusing
        # the same Img instance across calls is safe.
        self._sprite_cache: dict[pathlib.Path, Img] = {}

    def begin_frame(self) -> None:
        self._animator.forget_missing(self._piece_ids_drawn)
        self._piece_ids_drawn = set()

        self._frame = Img()
        if self._board_offset_x == 0:
            # A fresh Img sharing a *copy* of the board's pixels, so drawing
            # a piece/highlight never mutates the cached board image.
            self._frame.img = self._board.img.copy()
            return

        board_h, board_w = self._board.img.shape[:2]
        channels = self._board.img.shape[2]
        # Fully opaque dark gray panel background - alpha must be 255, not
        # 0, or the panels would come out fully transparent (and, depending
        # on how the frame is later consumed, show as unintended white/black
        # instead of a visible backdrop for the panel text).
        fill = (40, 40, 40, 255) if channels == 4 else (40, 40, 40)
        canvas = np.full((board_h, board_w + 2 * self._board_offset_x, channels), fill, dtype=self._board.img.dtype)
        canvas[:, self._board_offset_x:self._board_offset_x + board_w] = self._board.img
        self._frame.img = canvas

    def frame(self):
        return self._frame.img

    # The board background image already renders the checkered grid, so
    # per-cell rects would only paint over it - nothing to draw here.
    def draw_rect(self, x: int, y: int, width: int, height: int) -> None:
        pass

    # view/renderer.py resolves each piece's board row/col to its cell
    # *center* in pixels before calling here, but Img.draw_on takes a
    # top-left corner - shift by half the sprite size to compensate.
    #
    # key is "{piece_id}:{color}:{kind}:{state}" (see view/renderer.py) - the
    # id lets SpriteAnimator track how long this specific piece has been in
    # its current state, so its animation frame advances independently of
    # every other piece on the board.
    def draw_image(self, key: str, x: int, y: int) -> None:
        piece_id, color, kind, state = key.split(":")
        self._piece_ids_drawn.add(piece_id)
        code = piece_config.piece_code(kind, color)
        path = self._animator.sprite_path(piece_id, code, state)

        sprite = self._sprite_cache.get(path)
        if sprite is None:
            # Sprites are natively smaller than cell_size (e.g. 64x64 ->
            # 100x100) - this is an enlargement, not a shrink, so it needs
            # INTER_LINEAR (Img.read's own default, INTER_AREA, is meant
            # for shrinking and blurs when used to enlarge instead).
            sprite = Img().read(
                path, size=(self._cell_size, self._cell_size), keep_aspect=True, interpolation=cv2.INTER_LINEAR
            )
            self._sprite_cache[path] = sprite

        sprite_h, sprite_w = sprite.img.shape[:2]
        sprite.draw_on(self._frame, self._board_offset_x + x - sprite_w // 2, y - sprite_h // 2)

    # Solid, alpha-preserving fill for the moves-log/score side panel's
    # decorative card background/border/row-stripe rects (see
    # view/renderer.py's _draw_panel) - writes only the BGR channels, the
    # same trick draw_cooldown_bar below already uses, so panel decoration
    # never resets a frame pixel's alpha back to fully transparent.
    # Frame-absolute coordinates, not board-relative - same reasoning as
    # draw_text. Clamped to the frame's own bounds rather than trusting
    # numpy's slice clipping, since a negative x/y would otherwise wrap
    # around to the wrong edge instead of just being cropped.
    def fill_rect(self, x: int, y: int, width: int, height: int, color=(20, 20, 20)) -> None:
        frame = self._frame.img
        frame_h, frame_w = frame.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(frame_w, x + width), min(frame_h, y + height)
        if x1 <= x0 or y1 <= y0:
            return
        frame[y0:y1, x0:x1, :3] = color

    def highlight_cell(self, row: int, col: int, color=(0, 255, 255), alpha: float = 0.35) -> None:
        x, y = self._board_offset_x + col * self._cell_size, row * self._cell_size
        region = self._frame.img[y:y + self._cell_size, x:x + self._cell_size]
        overlay = region.copy()
        overlay[:, :, :3] = color
        region[:, :, :3] = (1 - alpha) * region[:, :, :3] + alpha * overlay[:, :, :3]

    # A depleting bar centered along a resting piece's cell's bottom edge -
    # fraction 1.0 draws it at its full (short) length, fraction 0.0 draws
    # nothing. Solid fill, not alpha-blended like highlight_cell above: this
    # is meant to read as a clock/timer, not a tint on the square
    # underneath it. color is BGR, like every other color this class takes
    # (cv2's own convention, see debug_mouse.py's HOVER_COLOR/CLICK_COLOR
    # for the same (B, G, R) ordering) - defaults to red.
    def draw_cooldown_bar(self, row: int, col: int, fraction: float, color=(0, 0, 255)) -> None:
        fraction = max(0.0, min(1.0, fraction))
        if fraction <= 0.0:
            return
        bar_height = max(1, round(self._cell_size * _COOLDOWN_BAR_HEIGHT_FRAC))
        full_bar_width = round(self._cell_size * _COOLDOWN_BAR_LENGTH_FRAC)
        bar_width = round(full_bar_width * fraction)
        x = self._board_offset_x + col * self._cell_size + (self._cell_size - full_bar_width) // 2
        y = row * self._cell_size + self._cell_size - bar_height
        self._frame.img[y:y + bar_height, x:x + bar_width, :3] = color

    # cv2.putText positions (x, y) at the text's baseline, not a top-left
    # corner - without compensating, y=0 (as Renderer's "Game Over" message
    # uses) would draw almost entirely above row 0 and be clipped off the
    # frame. Shifting down by the glyph height makes y behave like every
    # other draw_* call's top-left-origin convention.
    def draw_text(self, text: str, x: int, y: int, font_size: float = 1.0, color=(255, 255, 255, 255)) -> None:
        (_, text_height), _ = cv2.getTextSize(text, _TEXT_FONT, font_size, 1)
        self._frame.put_text(text, x, y + text_height, font_size, color=color)
