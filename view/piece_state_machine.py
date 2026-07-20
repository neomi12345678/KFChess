"""Explicit state machine for a piece's *displayed* animation state -
formalizes what view/canvas/sprite_frames.py's SpriteAnimator used to track
only as a private implementation detail (a folder name plus a timestamp).
GameEngine.snapshot() reports which real-time phase (model.piece.PHASE_IDLE/
PHASE_MOVE/PHASE_JUMP/PHASE_SHORT_REST/PHASE_LONG_REST) a piece is in - a
game-state fact, not a rendering instruction (see PieceSnapshot.motion_phase's
own docstring). This class is the one place that turns "GameEngine says this
piece is now in phase X" into "this piece has been continuously displaying
phase X for N seconds", and the one place a piece is forgotten once it stops
appearing at all (captured, or never yet seen) - so nothing here accumulates
state for pieces that no longer exist across a long game.
"""

import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable


@dataclass
class _Entry:
    phase: str
    entered_at: float


class PieceAnimationStateMachine:
    # clock is injectable so tests can control elapsed time deterministically
    # instead of sleeping in real time - same reasoning as every other
    # clock-taking constructor in view/.
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._entries: Dict[str, _Entry] = {}

    # Reports how many seconds `piece_id` has continuously been in `phase` -
    # resets to 0.0 the instant phase differs from whatever this piece was
    # last seen in (including the first time a piece_id is ever seen).
    def enter(self, piece_id: str, phase: str) -> float:
        now = self._clock()
        entry = self._entries.get(piece_id)
        if entry is None or entry.phase != phase:
            entry = _Entry(phase=phase, entered_at=now)
            self._entries[piece_id] = entry
        return now - entry.entered_at

    # Drops every tracked piece not in `present_piece_ids` - called once per
    # frame (see view/canvas/sprite_frames.py's SpriteAnimator.forget_missing)
    # with every id actually drawn that frame, so a captured piece's entry
    # doesn't linger forever.
    def forget_missing(self, present_piece_ids: Iterable[str]) -> None:
        present = set(present_piece_ids)
        for piece_id in list(self._entries):
            if piece_id not in present:
                del self._entries[piece_id]
