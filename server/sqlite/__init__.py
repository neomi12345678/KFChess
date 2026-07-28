"""SQLite-backed implementations of the shared stores/Protocols
server/accounts.py and server/rooms.py define - the default backing store
for a bare-metal `python -m server.main` run (see server/main.py's own
_build_stores for when the Postgres-backed siblings in server/postgres/
are used instead, gated behind DATABASE_URL).

    accounts_db.py    AccountsDatabase, open_accounts_database
    accounts.py       UserStore
    rating_store.py   RatingStore
    rooms.py          RoomStore
"""
