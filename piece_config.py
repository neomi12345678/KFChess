"""Reads assets/pieces/<code>/states/<state>/config.json for the
view/graphics side (what state comes next, frames_per_sec, is_loop, frame
count). No realtime/physics module reads from here - every gameplay-
affecting duration (move/jump/short_rest/long_rest) is a fixed game-design
constant in logic_config.py instead, so realtime/physics timing never
depends on this file's fields (frame count, frames_per_sec, or the
speed_m_per_sec this asset format happens to define) or on an asset even
existing.
"""

import json
import pathlib
from dataclasses import dataclass

from model.piece import COLOR_BY_LETTER, KIND_BY_LETTER

ASSETS_DIR = pathlib.Path(__file__).resolve().parent / "assets"
PIECES_DIR = ASSETS_DIR / "pieces"


# A named pair of asset roots - everything view/ reads from disk (piece
# sprites/config.json below, board.png in view/canvas/img_canvas.py) comes
# from one of these two paths, never from ASSETS_DIR/PIECES_DIR directly.
# Swapping which skin is in play is then just constructing a different Skin
# and passing it down (see SpriteAnimator/ImgCanvas), the same
# constructor-argument-not-global-config pattern already used for cell_size
# elsewhere in view/ - no registry or lookup-by-name needed until there's
# an actual second skin to select at runtime.
@dataclass(frozen=True)
class Skin:
    pieces_dir: pathlib.Path
    board_path: pathlib.Path


DEFAULT_SKIN = Skin(pieces_dir=PIECES_DIR, board_path=ASSETS_DIR / "board.png")

_KIND_LETTER_BY_WORD = {word: letter for letter, word in KIND_BY_LETTER.items()}
_COLOR_LETTER_BY_WORD = {word: letter for letter, word in COLOR_BY_LETTER.items()}


# "king"/"white" -> "KW" - the asset folder naming (kind-letter first, then
# color-letter, both uppercase), independent of boardio's board-notation
# letters (color-first and lowercase, e.g. "wK") since the two serve
# different purposes. Uppercasing the color letter here matters even though
# Windows' case-insensitive filesystem hides a mismatch - this breaks on
# case-sensitive filesystems (Linux/Mac) otherwise.
def piece_code(kind: str, color: str) -> str:
    return f"{_KIND_LETTER_BY_WORD[kind]}{_COLOR_LETTER_BY_WORD[color].upper()}"


@dataclass(frozen=True)
class AnimationConfig:
    next_state_when_finished: str
    frames_per_sec: int
    is_loop: bool
    frame_count: int


_cache: dict = {}


# Parses+caches the raw config.json + on-disk frame count once per
# (pieces_dir, code, state_folder) - the single place load_animation touches
# the filesystem. Keyed on pieces_dir too, not just (code, state_folder), so
# two skins that both have a "KW" idle state don't collide in this cache.
def _load_raw(pieces_dir: pathlib.Path, code: str, state_folder: str) -> dict:
    key = (pieces_dir, code, state_folder)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    state_dir = pieces_dir / code / "states" / state_folder
    with open(state_dir / "config.json", encoding="utf-8") as f:
        data = json.load(f)
    data["_frame_count"] = len(list((state_dir / "sprites").glob("*.png")))

    _cache[key] = data
    return data


# What view/canvas/sprite_frames.py imports - never carries speed_m_per_sec,
# which no layer reads anymore (see this module's docstring for why
# realtime/physics never derives timing from it). skin defaults to
# DEFAULT_SKIN so every existing caller keeps reading assets/pieces exactly
# as before.
def load_animation(code: str, state_folder: str, skin: Skin = DEFAULT_SKIN) -> AnimationConfig:
    data = _load_raw(skin.pieces_dir, code, state_folder)
    return AnimationConfig(
        next_state_when_finished=data["physics"]["next_state_when_finished"],
        frames_per_sec=data["graphics"]["frames_per_sec"],
        is_loop=data["graphics"]["is_loop"],
        frame_count=data["_frame_count"],
    )
