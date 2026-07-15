"""Reads assets/pieces/<code>/states/<state>/config.json - the single
source of truth physics/ (speed), realtime/ (what state comes next), and
graphics/ (frames_per_sec, is_loop, frame count) all read from, so none of
the three layers maintain separate copies of the same per-piece-per-state
data. jump/short_rest/long_rest durations are NOT read from here -
config.py's AIRBORNE_BASE_DURATION_MS/SHORT_REST_BASE_DURATION_MS/
LONG_REST_BASE_DURATION_MS own those, so realtime/physics timing never
depends on graphics-only fields like frame count or frames_per_sec.
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
class StateConfig:
    speed_m_per_sec: float
    next_state_when_finished: str
    frames_per_sec: int
    is_loop: bool
    frame_count: int


_cache: dict = {}


def load(code: str, state_folder: str) -> StateConfig:
    key = (code, state_folder)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    state_dir = PIECES_DIR / code / "states" / state_folder
    with open(state_dir / "config.json", encoding="utf-8") as f:
        data = json.load(f)
    frame_count = len(list((state_dir / "sprites").glob("*.png")))

    config = StateConfig(
        speed_m_per_sec=data["physics"]["speed_m_per_sec"],
        next_state_when_finished=data["physics"]["next_state_when_finished"],
        frames_per_sec=data["graphics"]["frames_per_sec"],
        is_loop=data["graphics"]["is_loop"],
        frame_count=frame_count,
    )
    _cache[key] = config
    return config
