import pathlib

import cv2

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
    def __init__(self, board_width: int = 8, board_height: int = 8):
        self._board = Img().read(BOARD_PATH, size=(board_width * CELL_SIZE, board_height * CELL_SIZE))
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
        # A fresh Img sharing a *copy* of the board's pixels, so drawing a
        # piece/highlight never mutates the cached board image.
        self._frame = Img()
        self._frame.img = self._board.img.copy()

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
        sprite.draw_on(self._frame, x - sprite_w // 2, y - sprite_h // 2)

    def highlight_cell(self, row: int, col: int, color=(0, 255, 255), alpha: float = 0.35) -> None:
        x, y = col * CELL_SIZE, row * CELL_SIZE
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
