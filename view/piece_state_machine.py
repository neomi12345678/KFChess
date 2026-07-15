"""A view-side state machine over motion_phase (model/game_state.py),
layering the one-shot rest states (long_rest/short_rest) on top of what
GameEngine reports (idle/move/jump) - see view/animation_states.py for
why the engine itself never produces long_rest/short_rest: it's a purely
visual concern belonging to the view, not to game state.

The transition table isn't hardcoded here - it's read from the same
per-state config.json (via piece_config.py) graphics/animation.py already
reads for frames_per_sec/is_loop, so both layers can never drift into
disagreeing about what comes next (move -> long_rest -> idle, jump ->
short_rest -> idle, idle -> idle).
"""

import time

import piece_config
from model.piece import PHASE_IDLE, PHASE_JUMP, PHASE_MOVE
from view.animation_states import STATE_FOLDER


class PieceStateMachine:
    """Tracks, per piece id, its *effective* animation state - which may be
    long_rest/short_rest even though GameEngine.snapshot() only ever
    reports idle/move/jump via PieceSnapshot.motion_phase.

    No cv2 dependency - just piece_config lookups and bookkeeping - so it's
    unit testable without a display. clock is injectable (like
    graphics/animation.py's SpriteAnimator) so tests can control elapsed
    time deterministically instead of sleeping in real time.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._entries: dict[str, tuple] = {}  # piece_id -> (state, entered_at)

    def state_for(self, piece_snapshot, piece_code: str) -> str:
        now = self._clock()
        engine_state = piece_snapshot.motion_phase

        if engine_state in (PHASE_MOVE, PHASE_JUMP):
            # The engine's own report is authoritative and immediate - a
            # piece can't be resting while it's actually moving/jumping.
            self._enter(piece_snapshot.id, engine_state, now)
            return engine_state

        entry = self._entries.get(piece_snapshot.id)
        if entry is None:
            self._enter(piece_snapshot.id, PHASE_IDLE, now)
            return PHASE_IDLE

        state, entered_at = entry
        if state == PHASE_IDLE:
            return PHASE_IDLE

        if state in (PHASE_MOVE, PHASE_JUMP):
            # The engine just reported idle right after move/jump - hand
            # off to whatever that clip's own config says comes next.
            state = self._next_state(piece_code, state)
            self._enter(piece_snapshot.id, state, now)
            return state

        # Resting (long_rest/short_rest): stay until this clip has played
        # through once, then hand off the same way.
        if self._clip_finished(piece_code, state, now - entered_at):
            state = self._next_state(piece_code, state)
            self._enter(piece_snapshot.id, state, now)

        return state

    def forget(self, piece_id: str) -> None:
        self._entries.pop(piece_id, None)

    def _enter(self, piece_id: str, state: str, now: float) -> None:
        self._entries[piece_id] = (state, now)

    def _next_state(self, piece_code: str, state: str) -> str:
        config = piece_config.load(piece_code, STATE_FOLDER[state])
        return config.next_state_when_finished

    def _clip_finished(self, piece_code: str, state: str, elapsed_s: float) -> bool:
        config = piece_config.load(piece_code, STATE_FOLDER[state])
        one_cycle_s = config.frame_count / config.frames_per_sec
        return elapsed_s >= one_cycle_s
