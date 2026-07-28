"""Entry point: python -m server.main"""

import asyncio
import logging
import os

from boardio.board_parser import parse as parse_board
from boardio.starting_position import STARTING_BOARD
from protocol.types import HOST as DEFAULT_HOST
from protocol.types import PORT as DEFAULT_PORT
from server.sqlite.accounts import UserStore
from server.sqlite.accounts_db import open_accounts_database
from server.sqlite.rating_store import RatingStore
from server.sqlite.rooms import RoomStore
from server.ws_server import GameServer

# Alongside this file, not CWD-relative - a real, persistent file (unlike
# tests, which each get their own ":memory:" accounts database/RoomStore -
# see server/sqlite/accounts_db.py's and server/sqlite/rooms.py's own
# db_path docstrings).
DB_PATH = os.path.join(os.path.dirname(__file__), "accounts.db")
ROOM_DB_PATH = os.path.join(os.path.dirname(__file__), "rooms.db")

# Overridable so a container can bind 0.0.0.0 (reachable from outside the
# container) while every bare-metal caller - and protocol/types.py's own
# HOST/PORT, which client_cli.py/play_online.py still connect to unchanged -
# keeps today's "localhost:8765" default. See docker-compose.yml.
HOST = os.environ.get("KFCHESS_HOST", DEFAULT_HOST)
PORT = int(os.environ.get("KFCHESS_PORT", DEFAULT_PORT))

_logger = logging.getLogger(__name__)


# Called fresh for every matched pair (see server/ws_server.py's
# board_factory) - a new game needs its own Board/pieces, not one reused
# (and thus stale with the previous game's captures) across games.
def _new_board():
    return parse_board(STARTING_BOARD)


# DATABASE_URL unset (the default, every bare-metal run) keeps today's
# SQLite files exactly as before. Set (see docker-compose.yml) switches to
# server/postgres/accounts.py's/server/postgres/rooms.py's Postgres-backed
# stores instead - imported lazily, right here, so a bare-metal run never
# needs psycopg installed just to import this module.
def _build_stores():
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        accounts_database = open_accounts_database(DB_PATH)
        return UserStore(accounts_database), RatingStore(accounts_database), RoomStore(ROOM_DB_PATH)

    from server.postgres.accounts import PostgresRatingStore, PostgresUserStore, open_postgres_accounts_database
    from server.postgres.rooms import PostgresRoomStore

    accounts_database = open_postgres_accounts_database(database_url)
    return (
        PostgresUserStore(accounts_database),
        PostgresRatingStore(accounts_database),
        PostgresRoomStore(database_url),
    )


# REDIS_URL unset (the default) keeps today's in-memory matchmaking queue
# exactly as before. Set (see docker-compose.yml) switches to
# server/redis/matchmaking.py's RedisMatchmakingQueue - imported lazily,
# same reasoning as _build_stores' own lazy psycopg import.
def _build_matchmaking():
    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None:
        return None

    from server.redis.matchmaking import RedisMatchmakingQueue

    return RedisMatchmakingQueue(redis_url)


# NATS_URL unset (the default) keeps today's behavior exactly as before -
# GameLoop treats no lifecycle_publisher as a pure no-op (see its own
# docstring). Set (see docker-compose.yml) switches to
# server/nats/lifecycle.py's NatsLifecyclePublisher - imported lazily, same
# reasoning as _build_stores'/_build_matchmaking's own lazy imports. Async,
# unlike those two, because connecting to NATS itself is an async call
# (nats.connect) - awaited once here at startup, not per-request.
async def _build_lifecycle_publisher():
    nats_url = os.environ.get("NATS_URL")
    if nats_url is None:
        return None

    from server.nats.lifecycle import NatsLifecyclePublisher

    return await NatsLifecyclePublisher.connect(nats_url)


async def _main() -> None:
    user_store, rating_store, room_store = _build_stores()
    matchmaking = _build_matchmaking()
    lifecycle_publisher = await _build_lifecycle_publisher()
    server = GameServer(
        _new_board,
        user_store,
        rating_store,
        host=HOST,
        port=PORT,
        room_store=room_store,
        matchmaking=matchmaking,
        lifecycle_publisher=lifecycle_publisher,
    )
    _logger.info("KFChess server listening on ws://%s:%s", HOST, PORT)
    await server.run_forever()


def main() -> None:  # pragma: no cover
    # The only place in the server package that configures logging output -
    # every other module (server/ws_server.py included) just calls
    # logging.getLogger(__name__) and trusts whoever runs the process to
    # have set this up, rather than each reaching for its own handler.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
