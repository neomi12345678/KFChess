"""ELO-proximity matchmaking queue for the Home screen's "Play" button -
pure bookkeeping, no I/O. server/ws_server.py owns the actual connections;
this only ever tracks who's currently waiting and decides who to pair up.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from server.interfaces import MatchmakingTick
from server.server_config import MATCHMAKING_STATUS_INTERVAL_MS, MATCHMAKING_TIMEOUT_MS, RATING_RANGE


@dataclass
class _Waiting:
    username: str
    rating: int
    waited_ms: int = 0
    last_notified_ms: int = 0


class MatchmakingQueue:
    # timeout_ms/status_interval_ms are injectable so tests can use values
    # measured in milliseconds instead of actually waiting out the real
    # 60-second default (see server/ws_server.py's own matchmaking_timeout_ms).
    def __init__(self, timeout_ms: int = MATCHMAKING_TIMEOUT_MS, status_interval_ms: int = MATCHMAKING_STATUS_INTERVAL_MS):
        # A plain dict, not a separate ordered list - insertion order is
        # preserved (Python 3.7+) and is exactly the "queued earlier" order
        # find_match needs, without tracking it twice.
        self._waiting: Dict[str, _Waiting] = {}
        self._timeout_ms = timeout_ms
        self._status_interval_ms = status_interval_ms

    # Replaces any previous entry wholesale rather than mutating one in
    # place - a re-enqueue (e.g. after a disconnect+rejoin) resets
    # waited_ms/last_notified_ms back to 0 for free, the same as a
    # first-time enqueue, with no special-case code (see
    # tests/unit/test_matchmaking_queue.py's own re-enqueue coverage).
    def enqueue(self, username: str, rating: int) -> None:
        self._waiting[username] = _Waiting(username=username, rating=rating)

    def remove(self, username: str) -> None:
        self._waiting.pop(username, None)

    def is_waiting(self, username: str) -> bool:
        return username in self._waiting

    # Ages every waiting entry by elapsed_ms in one pass and reports two
    # disjoint things about it: who just crossed timeout_ms unmatched
    # (removed from the queue as part of this same call - the caller
    # reports "can't find" for each and can assume they're already gone
    # afterward), and who just crossed a status_interval_ms notify boundary
    # while still waiting, paired with their own whole-seconds-remaining (an
    # entry that crosses both in the same call is only ever reported as
    # timed out - see the elif below - never a "N seconds left" heartbeat
    # one moment before the timeout that follows it).
    def advance_time(self, elapsed_ms: int) -> MatchmakingTick:
        timed_out: List[str] = []
        due_for_status: List[Tuple[str, int]] = []

        for username, waiting in self._waiting.items():
            waiting.waited_ms += elapsed_ms
            if waiting.waited_ms >= self._timeout_ms:
                timed_out.append(username)
            elif waiting.waited_ms - waiting.last_notified_ms >= self._status_interval_ms:
                # Resyncs to "now" rather than incrementing by
                # status_interval_ms - an unusually long tick that jumps
                # waited_ms past two or three boundaries at once still only
                # sends one status message this call, not a burst of
                # queued-up ones.
                waiting.last_notified_ms = waiting.waited_ms
                seconds_remaining = math.ceil((self._timeout_ms - waiting.waited_ms) / 1000)
                due_for_status.append((username, seconds_remaining))

        for username in timed_out:
            del self._waiting[username]

        return MatchmakingTick(timed_out=timed_out, due_for_status=due_for_status)

    # The first pair found within RATING_RANGE of each other, scanned in
    # queue (insertion) order - deterministic, and lets the caller treat
    # whichever username comes first in the returned tuple as "queued
    # earlier" (see server/ws_server.py's "first-queued becomes white").
    # Doesn't remove either from the queue itself - the caller does that
    # only once it's actually started a game for them.
    def find_match(self) -> Optional[Tuple[str, str]]:
        entries = list(self._waiting.values())

        for i, a in enumerate(entries):
            for b in entries[i + 1 :]:
                if abs(a.rating - b.rating) <= RATING_RANGE:
                    return (a.username, b.username)

        return None
