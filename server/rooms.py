"""Room registry for the Home screen's "Room" flow (create an id, join it,
cancel it) - the section-6 counterpart to server/matchmaking.py's
ELO-proximity PLAY queue: pure bookkeeping, no I/O beyond the SQLite
write-through below. server/ws_server.py owns the actual connections and
starts a GameSession once a room's second seat fills; this only ever tracks
which rooms exist, who's in them, and decides whether a joiner becomes the
opponent or a spectator.

RoomStore persists that same bookkeeping - who created a room, its
opponent, its spectators - so a room survives a server crash or restart
(unlike the GameSession itself, which is never persisted; see
server/ws_server.py's own docstring on how a room whose game was already
running resumes as a *fresh* game once both players reconnect, not a replay
of the board as it stood). Bundled into this module rather than a separate
file - unlike server/accounts.py's UserStore/server/rating_store.py's
RatingStore, room membership and room persistence are one and the same
concern here, not two genuinely distinct ones sharing a table.
"""

import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from protocol.types import Reason

_ID_LENGTH = 6


@dataclass
class Room:
    room_id: str
    creator: str
    opponent: Optional[str] = None
    spectators: Set[str] = field(default_factory=set)

    # A room stops being "joinable as the opponent" the instant a second
    # player fills it - every joiner after that is a spectator instead
    # (see RoomRegistry.join), and it's no longer cancellable (see
    # RoomRegistry.cancel) since a real game is what's now in progress.
    @property
    def is_pending(self) -> bool:
        return self.opponent is None


class RoomError(Exception):
    """Raised for a room request that can't be granted - not found, the
    caller's already elsewhere, wrong creator, already started. str(error)
    is itself the wire-ready protocol.types.Reason member (see
    server/ws_server.py's *_room_ack handlers), the same role
    server/accounts.py's InvalidCredentialsError plays for login."""


class RoomStore:
    """db_path has no default on purpose - same reasoning as
    server/accounts_db.py's open_accounts_database: every call site must
    say explicitly whether it means a real, persistent file
    (server/main.py) or an isolated ":memory:" database (RoomRegistry's
    own default below, and tests). Unlike the accounts database, nothing
    here ever runs off the asyncio event-loop thread (RoomRegistry's
    mutations are all synchronous calls from message handlers, never
    offloaded to an executor), so there's no need for
    check_same_thread=False or a lock.
    """

    def __init__(self, db_path: str):
        self._connection = sqlite3.connect(db_path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY,
                creator TEXT NOT NULL,
                opponent TEXT
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS room_spectators (
                room_id TEXT NOT NULL REFERENCES rooms(room_id),
                username TEXT NOT NULL,
                PRIMARY KEY (room_id, username)
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    # Upsert, called after every RoomRegistry mutation that leaves the room
    # in existence (create, join) - replaces the spectator rows wholesale
    # rather than diffing them, since a room's own spectator set is always
    # small and this only ever runs once per network message, not per tick.
    def save(self, room: Room) -> None:
        self._connection.execute(
            "INSERT INTO rooms (room_id, creator, opponent) VALUES (?, ?, ?) "
            "ON CONFLICT(room_id) DO UPDATE SET opponent = excluded.opponent",
            (room.room_id, room.creator, room.opponent),
        )
        self._connection.execute("DELETE FROM room_spectators WHERE room_id = ?", (room.room_id,))
        self._connection.executemany(
            "INSERT INTO room_spectators (room_id, username) VALUES (?, ?)",
            [(room.room_id, spectator) for spectator in room.spectators],
        )
        self._connection.commit()

    # Called once a room is gone for good - cancelled, or its game ended
    # (see RoomRegistry._forget, the single place both paths funnel
    # through) - so a finished room never lingers as stale data.
    def delete(self, room_id: str) -> None:
        self._connection.execute("DELETE FROM room_spectators WHERE room_id = ?", (room_id,))
        self._connection.execute("DELETE FROM rooms WHERE room_id = ?", (room_id,))
        self._connection.commit()

    # Plain dicts, not Room instances - this class has no need to depend on
    # Room's own constructor shape, only RoomRegistry.__init__ (the sole
    # caller) does. {"room_id", "creator", "opponent", "spectators"} per
    # room, spectators as a set.
    def load_all(self) -> List[dict]:
        rooms: Dict[str, dict] = {
            row[0]: {"room_id": row[0], "creator": row[1], "opponent": row[2], "spectators": set()}
            for row in self._connection.execute("SELECT room_id, creator, opponent FROM rooms")
        }
        for room_id, username in self._connection.execute("SELECT room_id, username FROM room_spectators"):
            rooms[room_id]["spectators"].add(username)
        return list(rooms.values())


class RoomRegistry:
    # store defaults to an isolated, disposable ":memory:" RoomStore -
    # every existing pure-in-memory call site (RoomRegistry()) keeps
    # working unchanged; only server/main.py passes a real, persistent
    # store.
    def __init__(self, store: Optional[RoomStore] = None):
        self._store = store if store is not None else RoomStore(":memory:")
        self._rooms: Dict[str, Room] = {}
        # A username is creator/opponent/spectator of at most one room at a
        # time - mirrors server/matchmaking.py's own "already queued" rule,
        # same reasoning: one connection, one concurrent game.
        self._room_id_by_username: Dict[str, str] = {}

        for row in self._store.load_all():
            room = Room(
                room_id=row["room_id"], creator=row["creator"], opponent=row["opponent"], spectators=row["spectators"]
            )
            self._rooms[room.room_id] = room
            self._room_id_by_username[room.creator] = room.room_id
            if room.opponent is not None:
                self._room_id_by_username[room.opponent] = room.room_id
            for spectator in room.spectators:
                self._room_id_by_username[spectator] = room.room_id

    def create(self, username: str) -> Room:
        if username in self._room_id_by_username:
            raise RoomError(Reason.ALREADY_IN_A_ROOM)

        room = Room(room_id=self._new_id(), creator=username)
        self._rooms[room.room_id] = room
        self._room_id_by_username[username] = room.room_id
        self._store.save(room)
        return room

    # The first join fills the opponent seat; every join after that is a
    # spectator - RoomRegistry itself doesn't care which, only reports it
    # back via the returned Room's own opponent/spectators (see
    # server/ws_server.py's _handle_join_room, which reads room.opponent ==
    # username to tell the two cases apart).
    def join(self, room_id: str, username: str) -> Room:
        room = self._rooms.get(room_id)
        if room is None:
            raise RoomError(Reason.ROOM_NOT_FOUND)
        if username in self._room_id_by_username:
            raise RoomError(Reason.ALREADY_IN_A_ROOM)

        if room.is_pending:
            room.opponent = username
        else:
            room.spectators.add(username)
        self._room_id_by_username[username] = room_id
        self._store.save(room)
        return room

    # Only the creator, and only before an opponent has joined - once a
    # room has a real game running, leaving it is a resignation/disconnect
    # (see server/session.py's own disconnect-grace handling), not a
    # cancellation.
    def cancel(self, username: str) -> None:
        room = self.room_for_username(username)
        if room is None:
            raise RoomError(Reason.NOT_IN_A_ROOM)
        if room.creator != username:
            raise RoomError(Reason.NOT_THE_CREATOR)
        if not room.is_pending:
            raise RoomError(Reason.ALREADY_STARTED)

        self._forget(room)

    def room_for_username(self, username: str) -> Optional[Room]:
        room_id = self._room_id_by_username.get(username)
        return self._rooms.get(room_id) if room_id is not None else None

    # Called once the room's own game actually ends (see
    # server/ws_server.py's _advance_game) - frees every member (creator,
    # opponent, every spectator) to create or join a new room, and drops
    # the room itself from the registry. A no-op if the room is already
    # gone (cancel() may have removed it already), same defensiveness as
    # server/matchmaking.py's own remove().
    def close(self, room_id: str) -> None:
        room = self._rooms.get(room_id)
        if room is not None:
            self._forget(room)

    def _forget(self, room: Room) -> None:
        del self._rooms[room.room_id]
        self._room_id_by_username.pop(room.creator, None)
        if room.opponent is not None:
            self._room_id_by_username.pop(room.opponent, None)
        for spectator in room.spectators:
            self._room_id_by_username.pop(spectator, None)
        self._store.delete(room.room_id)

    # Short and arbitrary (see the Home-screen slide's own room-id wording)
    # - collisions are checked and retried rather than assumed impossible,
    # the same defensiveness server/accounts.py's random salt doesn't need
    # (a salt has no uniqueness requirement at all) but a shared, guessable
    # keyspace like this one does.
    def _new_id(self) -> str:
        while True:
            candidate = uuid.uuid4().hex[:_ID_LENGTH]
            if candidate not in self._rooms:
                return candidate
