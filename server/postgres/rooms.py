"""PostgreSQL-backed sibling of server/sqlite/rooms.py's RoomStore, for the
Dockerized deployment (see docker-compose.yml, gated behind the
DATABASE_URL env var in server/main.py) - same save/delete/load_all/close
shape (server/rooms.py's own RoomStoreProtocol), just %s placeholders and
a psycopg connection instead of SQLite's "?". server/rooms.py's
RoomRegistry doesn't care which one it's handed; server/sqlite/rooms.py's
own RoomStore is untouched, and every existing test constructing it
against ":memory:" keeps working exactly as before.
"""

from typing import Dict, List

import psycopg

from server.rooms import Room


class PostgresRoomStore:
    def __init__(self, dsn: str):
        self._connection = psycopg.connect(dsn, autocommit=False)
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

    def save(self, room: Room) -> None:
        self._connection.execute(
            "INSERT INTO rooms (room_id, creator, opponent) VALUES (%s, %s, %s) "
            "ON CONFLICT (room_id) DO UPDATE SET opponent = excluded.opponent",
            (room.room_id, room.creator, room.opponent),
        )
        self._connection.execute("DELETE FROM room_spectators WHERE room_id = %s", (room.room_id,))
        # Unlike sqlite3.Connection, psycopg's Connection has no executemany
        # shortcut of its own - only Cursor does.
        if room.spectators:
            with self._connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO room_spectators (room_id, username) VALUES (%s, %s)",
                    [(room.room_id, spectator) for spectator in room.spectators],
                )
        self._connection.commit()

    def delete(self, room_id: str) -> None:
        self._connection.execute("DELETE FROM room_spectators WHERE room_id = %s", (room_id,))
        self._connection.execute("DELETE FROM rooms WHERE room_id = %s", (room_id,))
        self._connection.commit()

    def load_all(self) -> List[dict]:
        rooms: Dict[str, dict] = {
            row[0]: {"room_id": row[0], "creator": row[1], "opponent": row[2], "spectators": set()}
            for row in self._connection.execute("SELECT room_id, creator, opponent FROM rooms")
        }
        for room_id, username in self._connection.execute("SELECT room_id, username FROM room_spectators"):
            rooms[room_id]["spectators"].add(username)
        return list(rooms.values())
