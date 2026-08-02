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

from typing import List, Optional, Tuple

import psycopg

from server.postgres import commit_or_rollback, create_table_tolerating_concurrent_creation, rollback_after


class PostgresGameHistoryStore:
    def __init__(self, dsn: str):
        self._connection = psycopg.connect(dsn, autocommit=False)
        # Tolerates the concurrent-first-boot race (see
        # server/postgres/__init__.py's own docstring) - less likely here
        # (today's deployment only ever runs one Persistence Worker) but
        # cheap insurance against the same class of bug if that ever
        # changes, same reasoning as its sibling stores in this package.
        create_table_tolerating_concurrent_creation(
            self._connection,
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
            """,
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
        with commit_or_rollback(self._connection):
            self._connection.execute(
                """
                INSERT INTO game_history
                    (game_id, room_id, white_username, black_username, white_rating, black_rating)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (game_id) DO NOTHING
                """,
                (game_id, room_id, white_username, black_username, white_rating, black_rating),
            )

    # Server_Design.md §8's own "Persistence Workers consume it in batches" -
    # one executemany + one commit for the whole batch, not one INSERT/commit
    # round trip per game (see record_game above, still used directly by
    # tests/callers that want a single insert). games is the same
    # (game_id, room_id, white_username, black_username, white_rating,
    # black_rating) tuple shape record_game takes as separate args, just
    # batched - see services/persistence_worker/main.py's own
    # _tuple_from_payload, which builds these from game.finished payloads.
    def record_games_batch(
        self, games: List[Tuple[str, Optional[str], str, str, int, int]]
    ) -> None:
        if not games:
            return
        with commit_or_rollback(self._connection):
            with self._connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO game_history
                        (game_id, room_id, white_username, black_username, white_rating, black_rating)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (game_id) DO NOTHING
                    """,
                    games,
                )

    def all_games(self) -> List[dict]:
        # Same reasoning as server/postgres/rooms.py's own PostgresRoomStore.
        # load_all - a read-only SELECT under autocommit=False would
        # otherwise leave this connection idle in an open transaction
        # indefinitely, holding a lock that can block an unrelated
        # exclusive operation (e.g. a test fixture's own TRUNCATE)
        # elsewhere. rollback_after (see its own docstring) guarantees that
        # rollback runs even if execute()/fetchall() itself raises, not just
        # on success - .fetchall() still happens inside the block, not
        # lazily iterating the cursor in the list comprehension below, so
        # every row is read before the rollback ends the transaction.
        with rollback_after(self._connection):
            rows = self._connection.execute(
                "SELECT game_id, room_id, white_username, black_username, white_rating, black_rating "
                "FROM game_history ORDER BY finished_at"
            ).fetchall()
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
