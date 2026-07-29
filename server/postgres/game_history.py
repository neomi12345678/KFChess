"""PostgreSQL-backed durable game-history store - the "Persistence Worker"
role from Server_Design.md §3/§8/§11 (docs/server-scaling-design branch):
a stateless consumer of the `game.finished` control-plane event
(server/nats/lifecycle.py), writing final results to PostgreSQL, decoupled
from the Game Server Shard's own tick loop (see services/persistence_worker/main.py,
the standalone service that owns an instance of this class).

Same shape as server/postgres/rooms.py's PostgresRoomStore - a dsn-taking
constructor that owns its own connection and creates its table on first
use, %s placeholders instead of SQLite's "?". No SQLite counterpart exists
(unlike accounts/rooms): a bare-metal run has no separate Persistence
Worker to write through, so there's nothing to mirror there.
"""

from typing import List, Optional

import psycopg


class PostgresGameHistoryStore:
    def __init__(self, dsn: str):
        self._connection = psycopg.connect(dsn, autocommit=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS game_history (
                game_id TEXT PRIMARY KEY,
                room_id TEXT,
                white_username TEXT NOT NULL,
                black_username TEXT NOT NULL,
                white_rating INTEGER NOT NULL,
                black_rating INTEGER NOT NULL,
                finished_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    # ON CONFLICT DO NOTHING - idempotent, same defensive reasoning as this
    # project's ShardRegistry/room-ownership lease: cheap insurance against
    # a redelivered game.finished, even though core NATS pub/sub is
    # at-most-once and shouldn't ever actually redeliver one.
    def record_game(
        self,
        game_id: str,
        room_id: Optional[str],
        white_username: str,
        black_username: str,
        white_rating: int,
        black_rating: int,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO game_history
                (game_id, room_id, white_username, black_username, white_rating, black_rating)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (game_id) DO NOTHING
            """,
            (game_id, room_id, white_username, black_username, white_rating, black_rating),
        )
        self._connection.commit()

    def all_games(self) -> List[dict]:
        rows = self._connection.execute(
            "SELECT game_id, room_id, white_username, black_username, white_rating, black_rating "
            "FROM game_history ORDER BY finished_at"
        )
        return [
            {
                "game_id": row[0],
                "room_id": row[1],
                "white_username": row[2],
                "black_username": row[3],
                "white_rating": row[4],
                "black_rating": row[5],
            }
            for row in rows
        ]
