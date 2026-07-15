"""Reads assets/pieces/<code>/states/<state>/config.json - the single
source of truth physics/motion.py (speed) and the view/graphics side
(what state comes next, frames_per_sec, is_loop, frame count) both read
from, so the two never maintain separate copies of the same
per-piece-per-state data. jump/short_rest/long_rest durations are NOT read
from here - logic_config.py's AIRBORNE_BASE_DURATION_MS/SHORT_REST_BASE_DURATION_MS/
LONG_REST_BASE_DURATION_MS own those, so realtime/physics timing never
depends on graphics-only fields like frame count or frames_per_sec.

load_motion/load_animation split the same underlying file into two
narrow, layer-scoped shapes instead of one combined dataclass, so
physics/motion.py's only import from here can never carry animation
fields it has no business seeing (next_state_when_finished is filed
under the JSON's own "physics" key, but is consumed only by
view/piece_state_machine.py's animation-state transitions, never by
physics/motion.py itself) - both loaders share the same cached raw read
below, so there's still exactly one place that parses the file.
"""

import json
import pathlib
from dataclasses import dataclass

from model.piece import COLOR_BY_LETTER, KIND_BY_LETTER

ASSETS_DIR = pathlib.Path(__file__).resolve().parent / "assets"
PIECES_DIR = ASSETS_DIR / "pieces"

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
class MotionConfig:
    speed_m_per_sec: float


@dataclass(frozen=True)
class AnimationConfig:
    next_state_when_finished: str
    frames_per_sec: int
    is_loop: bool
    frame_count: int


_cache: dict = {}


# Parses+caches the raw config.json + on-disk frame count once per
# (code, state_folder), regardless of which of load_motion/load_animation
# asked for it first - the single place either loader touches the
# filesystem, so the two can never drift into reading the file differently.
def _load_raw(code: str, state_folder: str) -> dict:
    key = (code, state_folder)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    state_dir = PIECES_DIR / code / "states" / state_folder
    with open(state_dir / "config.json", encoding="utf-8") as f:
        data = json.load(f)
    data["_frame_count"] = len(list((state_dir / "sprites").glob("*.png")))

    _cache[key] = data
    return data


# The only piece of this file physics/motion.py ever imports - never
# carries next_state_when_finished/frames_per_sec/is_loop/frame_count,
# fields it has no use for and no business seeing.
def load_motion(code: str, state_folder: str) -> MotionConfig:
    data = _load_raw(code, state_folder)
    return MotionConfig(speed_m_per_sec=data["physics"]["speed_m_per_sec"])


# What graphics/animation.py and view/piece_state_machine.py import -
# never carries speed_m_per_sec, which is physics/motion.py's alone.
def load_animation(code: str, state_folder: str) -> AnimationConfig:
    data = _load_raw(code, state_folder)
    return AnimationConfig(
        next_state_when_finished=data["physics"]["next_state_when_finished"],
        frames_per_sec=data["graphics"]["frames_per_sec"],
        is_loop=data["graphics"]["is_loop"],
        frame_count=data["_frame_count"],
    )
