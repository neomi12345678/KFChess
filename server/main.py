"""Entry point: python -m server.main"""

import asyncio
import logging
import os

from boardio.board_parser import parse as parse_board
from boardio.starting_position import STARTING_BOARD
from protocol.types import HOST as DEFAULT_HOST
from protocol.types import PORT as DEFAULT_PORT
from server.logging_config import configure_logging
from server.observability_server import start_observability_server
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

# Server_Design.md §9's own health/readiness/metrics HTTP surface (see
# server/observability_server.py) - a distinct default port from every
# other service's own (see docker-compose.yml), overridable the same way
# every other port in this project already is.
HEALTH_PORT = int(os.environ.get("HEALTH_PORT", 9105))

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


# REDIS_URL unset (the default) keeps spectator-identify purely in-process
# (CommandRouter's own default of no remote room lookup at all) - fine for a
# single process, since a bare-metal server/ws_server.py's own
# _handle_join_room already adds a spectator to spectator_usernames
# synchronously, in-process, the instant they join. Set, this becomes the
# read-only, cross-process view of a standalone API Gateway's own room
# membership (see server/redis/rooms.py's RedisRoomRegistry) that
# decide_identify consults for a spectator who joined via REST instead (see
# its own docstring). No busy_set - this shard never creates/joins/cancels
# rooms through it, only reads room_for_username.
def _build_remote_rooms():
    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None:
        return None

    from server.redis.rooms import RedisRoomRegistry

    return RedisRoomRegistry(redis_url)


# REDIS_URL unset (the default) keeps every game purely in-memory, same as
# every other optional GameLoop dependency (GameLoop's own default of no
# fairness checkpoint at all) - fine for a single process, since a crash
# there takes the whole bare-metal process down anyway, nothing to hand a
# recovery sweep. Set, this persists Server_Design.md §9's own lightweight
# fairness checkpoint (see server/redis/fairness_checkpoint.py) so
# services/game_allocator/main.py's own recovery sweep has something to log
# if this shard dies mid-game.
def _build_fairness_checkpoint():
    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None:
        return None

    from server.redis.fairness_checkpoint import FairnessCheckpoint

    return FairnessCheckpoint(redis_url)


# REDIS_URL unset (the default) keeps presence untracked entirely - fine for
# a single bare-metal process with no other service that could ever ask "is
# this username online." Set, this is Server_Design.md §5's own "presence /
# session directory" (see server/redis/presence.py), marked online/offline
# right alongside this same shard's own login/identify/disconnect handling.
def _build_presence():
    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None:
        return None

    from server.redis.presence import Presence

    return Presence(redis_url)


# REDIS_URL unset (the default) skips the §4 room-ownership lease entirely -
# fine for a bare-metal run with no standalone Game Allocator to race
# against in the first place. Set, this is the same RoomShardIndex a
# standalone Game Allocator writes (see services/game_allocator/main.py) -
# this shard only ever renews/releases it, never sets it (see
# server/interfaces.py's RoomShardIndexProtocol, and
# server/redis/room_shard_index.py's own docstring on why set() stays the
# allocator's job).
def _build_room_shard_index():
    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None:
        return None

    from server.redis.room_shard_index import RoomShardIndex

    return RoomShardIndex(redis_url)


# Wraps rating_store so every update_rating call also keeps
# Server_Design.md §5's own Redis leaderboard (server/redis/leaderboard.py)
# in sync - see that module's own docstring for why GameSession.
# finalize_ratings_if_game_over is the one call site this needs to cover.
# REDIS_URL unset (the default) leaves rating_store untouched.
def _wrap_rating_store_with_leaderboard(rating_store):
    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None:
        return rating_store

    from server.redis.leaderboard import Leaderboard, LeaderboardRatingStore

    return LeaderboardRatingStore(rating_store, Leaderboard(redis_url))


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
def _maybe_start_shard_heartbeat(server: GameServer) -> None:
    shard_address = os.environ.get("SHARD_ADDRESS")
    if shard_address is None:
        return

    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None:
        _logger.warning("SHARD_ADDRESS is set but REDIS_URL is not - shard registration skipped")
        return

    from server.redis.shard_registry import ShardRegistry

    asyncio.create_task(_run_shard_heartbeat(ShardRegistry(redis_url), shard_address, server.active_game_count))


# interval_s is well under ShardRegistry's own default 10s TTL, so one slow
# tick never causes this shard to be seen as dead when it's not. room_count_fn
# is server.active_game_count - a callable, not a snapshotted int, so every
# heartbeat reports this shard's *current* load (Server_Design.md §9's own
# "bound the blast radius" - see server/redis/shard_registry.py's own
# pick_shard docstring), not whatever it was when this loop started.
async def _run_shard_heartbeat(registry, shard_address: str, room_count_fn, interval_s: float = 3.0) -> None:
    while True:
        registry.register(shard_address, room_count=room_count_fn())
        await asyncio.sleep(interval_s)


# Server_Design.md §9's own readiness probe - checks only the dependencies
# this shard was actually configured with (REDIS_URL/DATABASE_URL/NATS_URL
# all optional here, see this module's own "None is a no-op" convention
# throughout) via dedicated, synchronous clients of its own, safe to call
# from server/observability_server.py's own background thread. lifecycle_publisher
# is reused rather than opening a fourth NATS connection just for this -
# see its own connection property.
def _build_readiness_checks(redis_url, database_url, lifecycle_publisher) -> dict:
    checks = {}

    if redis_url is not None:
        import redis as redis_lib

        # Explicit, short timeouts - redis-py's own default is *no* timeout
        # at all, which would make an unreachable Redis hang this check
        # instead of failing it (see server/observability_server.py's own
        # docstring on why that matters here specifically).
        redis_client = redis_lib.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        checks["redis"] = lambda: bool(redis_client.ping())

    if database_url is not None:
        import psycopg

        def _check_postgres() -> bool:
            with psycopg.connect(database_url, connect_timeout=2) as connection:
                connection.execute("SELECT 1")
            return True

        checks["postgres"] = _check_postgres

    if lifecycle_publisher is not None:
        checks["nats"] = lambda: lifecycle_publisher.connection.is_connected

    return checks


async def _main() -> None:
    user_store, rating_store, room_store = _build_stores()
    rating_store = _wrap_rating_store_with_leaderboard(rating_store)
    matchmaking = _build_matchmaking()
    lifecycle_publisher = await _build_lifecycle_publisher()
    busy_set = _build_busy_set()
    active_game_index = _build_active_game_index()
    remote_rooms = _build_remote_rooms()
    fairness_checkpoint = _build_fairness_checkpoint()
    presence = _build_presence()
    room_shard_index = _build_room_shard_index()
    # Same env var _maybe_start_shard_heartbeat already reads below - handed
    # to GameServer/GameLoop too now, so every ActiveGameLocation this shard
    # writes carries its own real, reachable address (see
    # server/interfaces.py's ActiveGameLocation and services/ws_gateway/main.py,
    # which resolves a shard to open its own internal relay connection to).
    shard_address = os.environ.get("SHARD_ADDRESS")
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
        shard_address=shard_address,
        remote_rooms=remote_rooms,
        fairness_checkpoint=fairness_checkpoint,
        presence=presence,
        room_shard_index=room_shard_index,
    )
    await _build_matchmaking_relay(server)
    _maybe_start_shard_heartbeat(server)
    readiness_checks = _build_readiness_checks(
        os.environ.get("REDIS_URL"), os.environ.get("DATABASE_URL"), lifecycle_publisher
    )
    start_observability_server(HEALTH_PORT, readiness_checks)
    _logger.info("KFChess server listening on ws://%s:%s", HOST, PORT)
    await server.run_forever()


def main() -> None:  # pragma: no cover
    # The only place in the server package that configures logging output -
    # every other module (server/ws_server.py included) just calls
    # logging.getLogger(__name__) and trusts whoever runs the process to
    # have set this up, rather than each reaching for its own handler.
    configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
