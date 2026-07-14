import pathlib

import cv2
import numpy as np

import piece_config
from config import CELL_SIZE
from graphics.animation import SpriteAnimator
from graphics.img import Img

_TEXT_FONT = cv2.FONT_HERSHEY_SIMPLEX

BOARD_PATH = piece_config.ASSETS_DIR / "board.png"
PIECES_DIR = piece_config.PIECES_DIR


class ImgCanvas:
    """Implements the draw_rect/draw_image/highlight_cell/draw_text interface
    that view/renderer.py expects, using only graphics/img.py (Img) as the
    drawing backend.
    """

    # board.png's native resolution (828x822) doesn't divide evenly into
    # CELL_SIZE-sized cells - resizing it to exactly width*height cells here
    # is what keeps every piece aligned to its square instead of drifting.
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
    def __init__(self, board_width: int = 8, board_height: int = 8, side_panel_width_px: int = 0):
        self._board = Img().read(BOARD_PATH, size=(board_width * CELL_SIZE, board_height * CELL_SIZE))
        self._board_offset_x = side_panel_width_px
        self._frame = None
        self._animator = SpriteAnimator()
        # Every (piece_code, state, frame) sprite file's pixels never change
        # once loaded - reading + resizing it fresh from disk on every
        # draw_image call (every piece, every rendered frame) would be pure
        # waste, so cache the decoded Img by its resolved path. draw_on only
        # ever writes into the *target* frame, never mutates the sprite's
        # own pixels beyond a one-time channel-count conversion, so reusing
        # the same Img instance across calls is safe.
        self._sprite_cache: dict[pathlib.Path, Img] = {}

    def begin_frame(self) -> None:
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

    # GameEngine.snapshot() reports each piece's pixel_x/pixel_y as its cell
    # *center* (see engine/game_engine.py's _cell_center), but Img.draw_on
    # takes a top-left corner - shift by half the sprite size to compensate.
    #
    # key is "{piece_id}:{color}:{kind}:{state}" (see view/renderer.py) - the
    # id lets SpriteAnimator track how long this specific piece has been in
    # its current state, so its animation frame advances independently of
    # every other piece on the board.
    def draw_image(self, key: str, x: int, y: int) -> None:
        piece_id, color, kind, state = key.split(":")
        code = piece_config.piece_code(kind, color)
        path = self._animator.sprite_path(piece_id, code, state)

        sprite = self._sprite_cache.get(path)
        if sprite is None:
            sprite = Img().read(path, size=(CELL_SIZE, CELL_SIZE), keep_aspect=True)
            self._sprite_cache[path] = sprite

        sprite_h, sprite_w = sprite.img.shape[:2]
        sprite.draw_on(self._frame, self._board_offset_x + x - sprite_w // 2, y - sprite_h // 2)

    def highlight_cell(self, row: int, col: int, color=(0, 255, 255), alpha: float = 0.35) -> None:
        x, y = self._board_offset_x + col * CELL_SIZE, row * CELL_SIZE
        region = self._frame.img[y:y + CELL_SIZE, x:x + CELL_SIZE]
        overlay = region.copy()
        overlay[:, :, :3] = color
        region[:, :, :3] = (1 - alpha) * region[:, :, :3] + alpha * overlay[:, :, :3]

    # cv2.putText positions (x, y) at the text's baseline, not a top-left
    # corner - without compensating, y=0 (as Renderer's "Game Over" message
    # uses) would draw almost entirely above row 0 and be clipped off the
    # frame. Shifting down by the glyph height makes y behave like every
    # other draw_* call's top-left-origin convention.
    def draw_text(self, text: str, x: int, y: int, font_size: float = 1.0, color=(255, 255, 255, 255)) -> None:
        (_, text_height), _ = cv2.getTextSize(text, _TEXT_FONT, font_size, 1)
        self._frame.put_text(text, x, y + text_height, font_size, color=color)
