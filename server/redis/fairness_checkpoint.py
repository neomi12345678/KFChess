"""Redis-backed "lightweight fairness checkpoint" - the literal
Server_Design.md §9 requirement, quoted in full: "persist just enough to
Redis every few seconds (score, elapsed time, remaining pieces) - not
exact mid-flight animation state - so that on crash the system can make a
*fair* decision (void the game, no rating penalty, or immediately re-queue
both players) rather than a full resume."

Deliberately not a physics/animation snapshot - the design doc itself
already considered and rejected that (pieces mid-flight/mid-interception/
mid-cooldown can't be reconstructed without risking visibly wrong replays,
for a correctness benefit that's marginal given games are short - see §9's
own reasoning). This only ever answers "roughly how far along was this
game," never "resume it exactly."

Written periodically by server/game_loop.py's GameLoop._advance_game
(gated behind FAIRNESS_CHECKPOINT_INTERVAL_MS, server/server_config.py) for
every currently-active game, keyed by game_id (a room's own room_id, for a
room's game). Removed the same way ActiveGameIndex/BusySet already are,
both on an ordinary game-over and on a crash (see GameLoop's own
_advance_game/_fail_game). Read by services/game_allocator/main.py's own
recovery sweep - purely for its own warning-level log line, not to drive
any automated void-vs-re-queue branching (see that module's own docstring
on why this pass always voids).

Plain sync `redis` client, same reasoning as this package's other modules
(server/redis/busy_set.py, server/redis/active_game_index.py,
server/redis/room_shard_index.py): every call here is a cheap, local Redis
round-trip, not something worth a dedicated async client.

Note this module lives at server/redis/fairness_checkpoint.py, importing
the third-party `redis` package by its bare top-level name below - Python
3's imports are absolute by default, so `import redis` here resolves to
the installed library on sys.path, not to this package (server.redis)
importing itself.
"""

import json
from typing import Optional

import redis

from server.interfaces import FairnessSnapshot

_KEY_PREFIX = "kfchess:fairness_checkpoint:"


class FairnessCheckpoint:
    def __init__(self, redis_url: str):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    def set(self, game_id: str, snapshot: FairnessSnapshot) -> None:
        payload = {
            "white_score": snapshot.white_score,
            "black_score": snapshot.black_score,
            "elapsed_ms": snapshot.elapsed_ms,
            "white_pieces_remaining": snapshot.white_pieces_remaining,
            "black_pieces_remaining": snapshot.black_pieces_remaining,
        }
        self._redis.set(f"{_KEY_PREFIX}{game_id}", json.dumps(payload))

    def remove(self, game_id: str) -> None:
        self._redis.delete(f"{_KEY_PREFIX}{game_id}")

    def get(self, game_id: str) -> Optional[FairnessSnapshot]:
        raw = self._redis.get(f"{_KEY_PREFIX}{game_id}")
        if raw is None:
            return None
        payload = json.loads(raw)
        return FairnessSnapshot(
            white_score=payload["white_score"],
            black_score=payload["black_score"],
            elapsed_ms=payload["elapsed_ms"],
            white_pieces_remaining=payload["white_pieces_remaining"],
            black_pieces_remaining=payload["black_pieces_remaining"],
        )
