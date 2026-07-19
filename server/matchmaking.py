"""ELO-proximity matchmaking queue for the Home screen's "Play" button -
pure bookkeeping, no I/O. server/ws_server.py owns the actual connections;
this only ever tracks who's currently waiting and decides who to pair up.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

RATING_RANGE = 100
TIMEOUT_MS = 60_000


@dataclass
class _Waiting:
    username: str
    rating: int
    waited_ms: int = 0


class MatchmakingQueue:
    # timeout_ms is injectable so tests can use a timeout measured in
    # milliseconds instead of actually waiting out the real 60-second
    # default (see server/ws_server.py's own matchmaking_timeout_ms).
    def __init__(self, timeout_ms: int = TIMEOUT_MS):
        # A plain dict, not a separate ordered list - insertion order is
        # preserved (Python 3.7+) and is exactly the "queued earlier" order
        # find_match needs, without tracking it twice.
        self._waiting: Dict[str, _Waiting] = {}
        self._timeout_ms = timeout_ms

    def enqueue(self, username: str, rating: int) -> None:
        self._waiting[username] = _Waiting(username=username, rating=rating)

    def remove(self, username: str) -> None:
        self._waiting.pop(username, None)

    def is_waiting(self, username: str) -> bool:
        return username in self._waiting

    # Ages every waiting entry by elapsed_ms and returns whichever
    # usernames just crossed timeout_ms unmatched, removing them from the
    # queue as part of the same call - the caller reports "can't find" for
    # each and can assume they're already gone from the queue afterward.
    def advance_time(self, elapsed_ms: int) -> List[str]:
        expired = []
        for username, waiting in self._waiting.items():
            waiting.waited_ms += elapsed_ms
            if waiting.waited_ms >= self._timeout_ms:
                expired.append(username)

        for username in expired:
            del self._waiting[username]

        return expired

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
