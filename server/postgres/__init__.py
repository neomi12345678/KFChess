"""PostgreSQL-backed siblings of server/sqlite/'s stores
(server/sqlite/accounts_db.py's AccountsDatabase, server/sqlite/accounts.py's
UserStore, server/sqlite/rating_store.py's RatingStore,
server/sqlite/rooms.py's RoomStore) - used only when the Dockerized
deployment sets DATABASE_URL (see server/main.py's _build_stores and
docker-compose.yml). The SQLite originals are untouched and stay the
default for a bare-metal run.

    accounts.py   PostgresAccountsDatabase, PostgresUserStore, PostgresRatingStore
    rooms.py      PostgresRoomStore
"""
