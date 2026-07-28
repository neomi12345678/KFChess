"""SQLite-backed RoomStore - persists server/rooms.py's RoomRegistry
bookkeeping (who created a room, its opponent, its spectators) so a room
survives a server crash or restart (unlike the GameSession itself, which
is never persisted; see server/ws_server.py's own docstring on how a room
whose game was already running resumes as a *fresh* game once both
players reconnect, not a replay of the board as it stood). See
server/postgres/rooms.py's PostgresRoomStore for the Postgres-backed
sibling server/main.py's _build_stores picks between (gated behind
DATABASE_URL) - both satisfy server/rooms.py's RoomStoreProtocol.

db_path has no default on purpose - same reasoning as
server/sqlite/accounts_db.py's open_accounts_database: every call site
must say explicitly whether it means a real, persistent file
(server/main.py) or an isolated ":memory:" database (RoomRegistry's own
default, and tests). Unlike the accounts database, nothing here ever runs
off the asyncio event-loop thread (RoomRegistry's mutations are all
synchronous calls from message handlers, never offloaded to an executor),
so there's no need for check_same_thread=False or a lock.
"""

import sqlite3
from typing import Dict, List

from server.rooms import Room


class RoomStore:
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
