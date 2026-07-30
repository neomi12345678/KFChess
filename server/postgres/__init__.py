"""PostgreSQL-backed siblings of server/sqlite/'s stores
(server/sqlite/accounts_db.py's AccountsDatabase, server/sqlite/accounts.py's
UserStore, server/sqlite/rating_store.py's RatingStore,
server/sqlite/rooms.py's RoomStore) - used only when the Dockerized
deployment sets DATABASE_URL (see server/main.py's _build_stores and
docker-compose.yml). The SQLite originals are untouched and stay the
default for a bare-metal run.

    accounts.py       PostgresAccountsDatabase, PostgresUserStore, PostgresRatingStore
    rooms.py          PostgresRoomStore
    game_history.py   PostgresGameHistoryStore (used by services/persistence_worker/main.py, not server/main.py)
"""

import psycopg


# Every store in this package runs its own CREATE TABLE IF NOT EXISTS on
# construction - fine for one process, but Server_Design.md §8's own "never
# one container per game" means multiple Game Server Shards (docker-compose.yml's
# game-server/game-server-2) construct their stores concurrently against a
# freshly initialized (still-empty) database on first boot. IF NOT EXISTS
# only guards the *statement*, not the race between two sessions that both
# see "doesn't exist yet" before either commits - Postgres can raise a
# genuine UniqueViolation on the underlying system catalog (pg_type) when
# both then try to actually create it, a real failure this project's own
# docker-compose stack hit the first time it ever booted against a
# completely empty postgres-data volume with two shards starting at once.
# Both outcomes ("I created it" and "someone else just did, in the
# instant between my own check and create") mean the same thing by the
# time this returns - the table exists - so the latter is swallowed rather
# than left to crash the whole process.
def create_table_tolerating_concurrent_creation(connection: "psycopg.Connection", sql: str) -> None:
    try:
        connection.execute(sql)
    except psycopg.errors.UniqueViolation:
        connection.rollback()
