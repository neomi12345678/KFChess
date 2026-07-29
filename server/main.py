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


# REDIS_URL unset (the default) keeps room/game busy-tracking purely
# in-memory (RoomRegistry/GameLoop's own default of no busy set at all) -
# fine for a single process, since it's the only thing that ever needs to
# know. Set, this becomes the cross-process source of truth a standalone
# api-gateway's PLAY busy-check reads (see server/redis/busy_set.py).
def _build_busy_set():
    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None:
        return None

    from server.redis.busy_set import BusySet

    return BusySet(redis_url)


# REDIS_URL unset (the default) keeps reconnect-detection purely in-process
# (GameLoop's own default of no active-game index at all) - fine for a
# single process, since decide_login already answers this in-process there.
# Set, this becomes the cross-process source of truth a standalone
# api-gateway's POST /login reads to answer "is this a reconnect, and to
# which color" (see server/redis/active_game_index.py).
def _build_active_game_index():
    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None:
        return None

    from server.redis.active_game_index import ActiveGameIndex

    return ActiveGameIndex(redis_url)


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


# NATS_URL unset skips the relay entirely - GameLoop keeps polling its own
# matchmaking queue locally, exactly as before (see GameLoop's own
# _matchmaker_is_external default of False). Set, this subscribes to the
# standalone Matchmaker service's matchmaking.status/matchmaking.timeout
# events regardless (harmless even with no separate Matchmaker running -
# nothing publishes them, so nothing arrives). EXTERNAL_MATCHMAKER=1 is the
# separate opt-in that actually stops GameLoop's own local polling - see
# GameLoop.start_matchmaking_relay's own docstring for why these can't be
# the same flag: NATS_URL is already set today (Step 1's deployment) purely
# for game-created/game-finished lifecycle events, with no separate
# Matchmaker service running at all - reusing it here would silently break
# that deployment by disabling local polling with nothing to replace it.
async def _build_matchmaking_relay(server: GameServer) -> None:
    nats_url = os.environ.get("NATS_URL")
    if nats_url is None:
        return

    import nats

    connection = await nats.connect(nats_url)
    external = os.environ.get("EXTERNAL_MATCHMAKER") == "1"
    await server.start_matchmaking_relay(connection, external=external)
    # Same connection, a second subscription - see
    # GameLoop.start_game_allocation_relay's own docstring for why this is
    # harmless to set up even without a standalone Game Allocator actually
    # running (nothing publishes game.allocated, so nothing arrives).
    await server.start_game_allocation_relay(connection)


# SHARD_ADDRESS unset (the default) skips shard registration entirely - a
# bare-metal run, or any deployment not meant to receive matched games, has
# nothing to register. Set alongside REDIS_URL (see docker-compose.yml),
# this starts a background heartbeat task that keeps this shard's own
# entry alive in server/redis/shard_registry.py's ShardRegistry - the Game
# Allocator discovers and picks a live shard from there instead of being
# told a fixed address up front (see services/game_allocator/main.py). SHARD_ADDRESS
# set without REDIS_URL is a misconfiguration - logged and skipped, not
# raised, matching every other opt-in feature's own "fail soft" convention
# in this module.
def _maybe_start_shard_heartbeat() -> None:
    shard_address = os.environ.get("SHARD_ADDRESS")
    if shard_address is None:
        return

    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None:
        _logger.warning("SHARD_ADDRESS is set but REDIS_URL is not - shard registration skipped")
        return

    from server.redis.shard_registry import ShardRegistry

    asyncio.create_task(_run_shard_heartbeat(ShardRegistry(redis_url), shard_address))


# interval_s is well under ShardRegistry's own default 10s TTL, so one slow
# tick never causes this shard to be seen as dead when it's not.
async def _run_shard_heartbeat(registry, shard_address: str, interval_s: float = 3.0) -> None:
    while True:
        registry.register(shard_address)
        await asyncio.sleep(interval_s)


async def _main() -> None:
    user_store, rating_store, room_store = _build_stores()
    matchmaking = _build_matchmaking()
    lifecycle_publisher = await _build_lifecycle_publisher()
    busy_set = _build_busy_set()
    active_game_index = _build_active_game_index()
    server = GameServer(
        _new_board,
        user_store,
        rating_store,
        host=HOST,
        port=PORT,
        room_store=room_store,
        matchmaking=matchmaking,
        lifecycle_publisher=lifecycle_publisher,
        busy_set=busy_set,
        active_game_index=active_game_index,
    )
    await _build_matchmaking_relay(server)
    _maybe_start_shard_heartbeat()
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
