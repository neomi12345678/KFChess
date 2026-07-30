"""Typed payload contracts for every internal NATS control-plane subject
this project's services publish/subscribe - matchmaking.requested,
matchmaking.status, matchmaking.timeout, match.found, room.opponent_joined,
game.allocated, game.created, game.finished (see each service's own
docstring - services/matchmaker/main.py, services/api_gateway/main.py,
services/game_allocator/main.py, services/ws_gateway/main.py,
server/game_loop.py, server/nats/lifecycle.py,
services/persistence_worker/main.py - for who publishes/subscribes to
which).

Before this module, every one of those call sites built or read the
payload as a raw dict via json.dumps/json.loads with a string key
(payload["white_username"]) - correct only by convention between whichever
two services happen to agree on the same key names, never checked by
anything. One dataclass per subject instead: a publisher constructs one and
calls .encode(), a subscriber calls Subject.decode(msg.data) and gets back
real attributes - a typo in a field name is now a NameError/AttributeError
at the call site instead of a silent KeyError three services away.

Deliberately not protocol/'s MessageType-based registry
(protocol/registry.py): that pattern exists because one websocket
connection carries many different message types and the receiving end must
dispatch on a runtime tag to know which one arrived. Here, the NATS subject
string itself is that tag - nats_connection.subscribe(subject, cb=...) only
ever calls its callback for messages already known to be that one subject -
so a second dispatch layer on top would be pure overhead. Each class's own
SUBJECT is what every publish/subscribe call site should pass instead of
repeating the literal string.

The wire format (the JSON actually sent over NATS) is unchanged by this
module - every field name/shape here matches exactly what the previous
hand-built dicts already used, so a rolling deploy mixing old and new code,
and every existing test that still publishes/reads a raw dict against these
same subjects, keeps working unmodified.
"""

import json
from dataclasses import asdict, dataclass
from typing import ClassVar, Dict, Optional


class _NatsEvent:
    # Identical for every subclass below (all fields are plain JSON-
    # compatible types - str/int/float/None/dict) - decode() stays a
    # per-class classmethod instead, since which fields are required vs.
    # read defensively via payload.get(...) genuinely differs per subject
    # (see GameAllocated.room_id/GameFinished.published_at below) and
    # deserves to be readable at each call site, not hidden behind a
    # generic reflection-based decoder.
    def encode(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")


@dataclass(frozen=True)
class MatchmakingRequested(_NatsEvent):
    SUBJECT: ClassVar[str] = "matchmaking.requested"
    username: str
    rating: int

    @classmethod
    def decode(cls, raw: bytes) -> "MatchmakingRequested":
        payload = json.loads(raw)
        return cls(username=payload["username"], rating=payload["rating"])


@dataclass(frozen=True)
class MatchmakingStatus(_NatsEvent):
    SUBJECT: ClassVar[str] = "matchmaking.status"
    username: str
    seconds_remaining: int

    @classmethod
    def decode(cls, raw: bytes) -> "MatchmakingStatus":
        payload = json.loads(raw)
        return cls(username=payload["username"], seconds_remaining=payload["seconds_remaining"])


@dataclass(frozen=True)
class MatchmakingTimeout(_NatsEvent):
    SUBJECT: ClassVar[str] = "matchmaking.timeout"
    username: str

    @classmethod
    def decode(cls, raw: bytes) -> "MatchmakingTimeout":
        return cls(username=json.loads(raw)["username"])


@dataclass(frozen=True)
class MatchFound(_NatsEvent):
    SUBJECT: ClassVar[str] = "match.found"
    white_username: str
    black_username: str

    @classmethod
    def decode(cls, raw: bytes) -> "MatchFound":
        payload = json.loads(raw)
        return cls(white_username=payload["white_username"], black_username=payload["black_username"])


@dataclass(frozen=True)
class RoomOpponentJoined(_NatsEvent):
    SUBJECT: ClassVar[str] = "room.opponent_joined"
    room_id: str
    creator: str
    opponent: str

    @classmethod
    def decode(cls, raw: bytes) -> "RoomOpponentJoined":
        payload = json.loads(raw)
        return cls(room_id=payload["room_id"], creator=payload["creator"], opponent=payload["opponent"])


@dataclass(frozen=True)
class GameAllocated(_NatsEvent):
    SUBJECT: ClassVar[str] = "game.allocated"
    game_id: str
    room_id: Optional[str]
    white_username: str
    black_username: str
    shard_address: str

    @classmethod
    def decode(cls, raw: bytes) -> "GameAllocated":
        payload = json.loads(raw)
        return cls(
            game_id=payload["game_id"],
            # None for a PLAY match (see this project's own convention -
            # services/game_allocator/main.py's _allocate) - .get, not
            # [...], the same defensive read every existing call site
            # already used.
            room_id=payload.get("room_id"),
            white_username=payload["white_username"],
            black_username=payload["black_username"],
            shard_address=payload["shard_address"],
        )


@dataclass(frozen=True)
class GameCreated(_NatsEvent):
    SUBJECT: ClassVar[str] = "game.created"
    game_id: str
    room_id: Optional[str]
    white_username: str
    black_username: str

    @classmethod
    def decode(cls, raw: bytes) -> "GameCreated":
        payload = json.loads(raw)
        return cls(
            game_id=payload["game_id"],
            room_id=payload.get("room_id"),
            white_username=payload["white_username"],
            black_username=payload["black_username"],
        )


@dataclass(frozen=True)
class GameFinished(_NatsEvent):
    SUBJECT: ClassVar[str] = "game.finished"
    game_id: str
    room_id: Optional[str]
    white_username: str
    black_username: str
    ratings: Dict[str, int]
    # Optional - see services/persistence_worker/main.py's own docstring:
    # "a newer field older publishers/tests may not send", read
    # defensively here the same way that module already reads it.
    published_at: Optional[float]

    @classmethod
    def decode(cls, raw: bytes) -> "GameFinished":
        payload = json.loads(raw)
        return cls(
            game_id=payload["game_id"],
            room_id=payload.get("room_id"),
            white_username=payload["white_username"],
            black_username=payload["black_username"],
            ratings=payload["ratings"],
            published_at=payload.get("published_at"),
        )
