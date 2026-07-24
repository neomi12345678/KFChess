"""Wall-clock-to-simulated-ms conversion shared by every real-time tick loop
in this project: play.py's local GUI frame loop and server/game_loop.py's
GameLoop.run_forever both advance a game by real elapsed wall-clock time, and
both need the same fractional-millisecond carry (see FrameClock.tick below)
so neither simulated clock drifts behind the wall clock by truncating a
fraction of a millisecond away every single tick. Previously duplicated
verbatim in both places; this is the one copy of that arithmetic.
"""

import time


class FrameClock:
    # Starts counting from construction time, not from the first tick() call
    # - a caller builds one right before entering its loop either way, so
    # there's no meaningful "elapsed" to report for a tick that hasn't
    # happened yet.
    def __init__(self):
        self._last_tick = time.monotonic()
        self._carried_ms = 0.0

    # Whole milliseconds elapsed since the previous tick() call (or since
    # construction, for the first one) - truncating each call's own
    # fractional remainder and carrying it into the next call instead of
    # discarding it is what keeps many small calls summing to the same real
    # elapsed time as one big one would.
    def tick(self) -> int:
        now = time.monotonic()
        elapsed_ms = (now - self._last_tick) * 1000 + self._carried_ms
        whole_ms = int(elapsed_ms)
        self._carried_ms = elapsed_ms - whole_ms
        self._last_tick = now
        return whole_ms
