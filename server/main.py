"""Entry point: python -m server.main"""

import asyncio
import contextlib
import logging
import os
import signal
from typing import Optional, Tuple

from boardio.board_parser import parse as parse_board
from boardio.starting_position import STARTING_BOARD
from protocol.types import HOST as DEFAULT_HOST
from protocol.types import PORT as DEFAULT_PORT
from server.logging_config import configure_logging
from server.nats.client import connect as connect_nats
from server.observability_server import start_observability_server
from server.server_config import MAX_ROOMS_PER_SHARD, SHARD_DRAIN_TIMEOUT_MS
from server.sqlite.accounts import UserStore
from server.sqlite.accounts_db import open_accounts_database
from server.sqlite.rating_store import RatingStore
from server.sqlite.rooms import RoomStore
from server.ws_server import GameServer
from tls_config import get_server_ssl_context

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

# SSL_CERT_FILE/SSL_KEY_FILE both unset (the default) keeps today's
# plaintext ws:// behavior - see tls_config.py's own docstring. Set (see
# docker-compose.yml/k8s's own commented-out example), this shard speaks
# wss:// to whatever connects to it directly instead - relevant for a
# bare-metal/direct deployment with no WS Gateway in front of it at all
# (see README's own `python -m server.main` + `python play_online.py`).
# When a WS Gateway *is* in front of this shard, its own internal relay
# hop stays plain ws:// regardless (see services/ws_gateway/main.py's own
# _relay) - Server_Design.md §3's own "Game Server Shards carry no public
# IP at all" already keeps that hop inside the compose/cluster network,
# out of reach of anything this cert would protect against.
SSL_CONTEXT = get_server_ssl_context(os.environ.get("SSL_CERT_FILE"), os.environ.get("SSL_KEY_FILE"))

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


# SESSION_TOKEN_SECRET unset (the default) lets GameServer's own __init__
# generate a fresh random secret for this one process - safe here, since a
# bare-metal shard both issues (LOGIN) and verifies (IDENTIFY) session
# tokens itself, same reasoning as every other REDIS_URL-gated "None is a
# no-op" default in this module. Set (see docker-compose.yml), this must be
# the same secret services/api_gateway/main.py issues tokens with -
# required the moment a standalone API Gateway sits in front of this shard
# instead of a bare-metal client logging in directly here, since issuing
# and verifying then happen in two different processes.
def _build_session_secret() -> Optional[bytes]:
    secret = os.environ.get("SESSION_TOKEN_SECRET")
    if secret is None:
        return None
    return secret.encode("utf-8")


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

    connection = await connect_nats(nats_url)
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
#
# Returns the heartbeat task plus a draining Event _main's own SIGTERM
# handling flips (see below) - None if there's nothing to drain (no
# heartbeat was ever started).
def _maybe_start_shard_heartbeat(server: GameServer) -> Optional[Tuple["asyncio.Task", asyncio.Event]]:
    shard_address = os.environ.get("SHARD_ADDRESS")
    if shard_address is None:
        return None

    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None:
        _logger.warning("SHARD_ADDRESS is set but REDIS_URL is not - shard registration skipped")
        return None

    from server.redis.shard_registry import ShardRegistry

    draining = asyncio.Event()
    task = asyncio.create_task(
        _run_shard_heartbeat(ShardRegistry(redis_url), shard_address, server.active_game_count, draining)
    )
    return task, draining


# interval_s is well under ShardRegistry's own default 10s TTL, so one slow
# tick never causes this shard to be seen as dead when it's not. room_count_fn
# is server.active_game_count - a callable, not a snapshotted int, so every
# heartbeat reports this shard's *current* load (Server_Design.md §9's own
# "bound the blast radius" - see server/redis/shard_registry.py's own
# pick_shard docstring), not whatever it was when this loop started.
#
# draining is set once _main's own SIGTERM handling begins Server_Design.md
# §8's own "stops accepting new rooms" - reporting MAX_ROOMS_PER_SHARD
# (never a real, lower count) from that point on is what makes
# ShardRegistry.pick_shard's own capacity filter exclude this shard from
# every *new* allocation, while this heartbeat itself keeps running -
# deliberately NOT deregistering outright, so services/game_allocator/main.py's
# own recovery sweep keeps seeing this shard as alive and doesn't
# prematurely void the very games this drain is trying to let finish
# naturally (a dead shard and a draining-but-still-ticking one need to look
# different to that sweep, not the same).
async def _run_shard_heartbeat(
    registry, shard_address: str, room_count_fn, draining: asyncio.Event, interval_s: float = 3.0
) -> None:
    while True:
        room_count = MAX_ROOMS_PER_SHARD if draining.is_set() else room_count_fn()
        registry.register(shard_address, room_count=room_count)
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
    session_secret = _build_session_secret()
    server = GameServer(
        _new_board,
        user_store,
        rating_store,
        host=HOST,
        port=PORT,
        ssl_context=SSL_CONTEXT,
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
        session_secret=session_secret,
    )
    await _build_matchmaking_relay(server)
    heartbeat = _maybe_start_shard_heartbeat(server)
    readiness_checks = _build_readiness_checks(
        os.environ.get("REDIS_URL"), os.environ.get("DATABASE_URL"), lifecycle_publisher
    )
    start_observability_server(HEALTH_PORT, readiness_checks)
    scheme = "wss" if SSL_CONTEXT is not None else "ws"
    _logger.info("KFChess server listening on %s://%s:%s", scheme, HOST, PORT)
    await _run_until_drained(server, heartbeat)


# Server_Design.md §8's own "a Game-Authority pod being retired stops
# accepting new rooms, drains its existing ones (bounded <=90s wait), then
# exits" - previously a known, self-flagged gap (see k8s/70-game-server.yaml's
# own comment): a SIGTERM'd pod just had its games end the same way any
# other crash does. run_forever() itself never returns on its own, so this
# runs it as a background task and races it against a SIGTERM-triggered
# Event instead of awaiting run_forever() directly - the same "wait for
# whichever happens first" shape as GameLoop's own per-game try/except one
# level down, just at process scope.
async def _run_until_drained(
    server: GameServer, heartbeat: Optional[Tuple["asyncio.Task", asyncio.Event]]
) -> None:
    run_task = asyncio.create_task(server.run_forever())

    # signal.signal, not loop.add_signal_handler - the latter raises
    # NotImplementedError on Windows' default ProactorEventLoop; this
    # module's own real target is a Linux container (docker-compose.yml/
    # k8s), where SIGTERM is exactly what `docker stop`/a Kubernetes pod
    # eviction actually sends, but registration itself must not crash a
    # bare-metal dev run on any platform. call_soon_threadsafe is what
    # makes it safe to flip an asyncio.Event from inside a signal handler,
    # which otherwise runs interleaved with - not on - the event loop.
    loop = asyncio.get_event_loop()
    shutdown_requested = asyncio.Event()
    signal.signal(signal.SIGTERM, lambda signum, frame: loop.call_soon_threadsafe(shutdown_requested.set))

    await _wait_then_drain(server, heartbeat, run_task, shutdown_requested)


# Split from _run_until_drained so tests/unit/test_server_main.py can
# simulate "SIGTERM arrived" by just setting shutdown_requested directly,
# without needing a real OS signal delivered to the test process itself
# (unreliable to depend on cross-platform, and irrelevant to what this
# function actually needs to get right: waiting for either run_forever()
# to fail or a shutdown request, then draining with a bound).
async def _wait_then_drain(
    server: GameServer,
    heartbeat: Optional[Tuple["asyncio.Task", asyncio.Event]],
    run_task: "asyncio.Task",
    shutdown_requested: asyncio.Event,
    # Overridable so tests can use a bound of milliseconds, not the real
    # 90s default - every real caller (_run_until_drained) omits this.
    drain_timeout_ms: int = SHARD_DRAIN_TIMEOUT_MS,
) -> None:
    shutdown_task = asyncio.create_task(shutdown_requested.wait())

    done, _pending = await asyncio.wait({run_task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED)

    if run_task in done:
        # run_forever() has no natural exit - reaching here means it
        # actually raised. Surface that instead of silently sitting here
        # forever waiting for a shutdown request that was never the reason
        # this needs to end.
        shutdown_task.cancel()
        run_task.result()
        return

    _logger.info("shutdown requested - draining before exit (up to %sms)", drain_timeout_ms)
    if heartbeat is not None:
        _, draining = heartbeat
        draining.set()

    deadline = asyncio.get_event_loop().time() + drain_timeout_ms / 1000
    while server.active_game_count() > 0 and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)

    remaining = server.active_game_count()
    if remaining > 0:
        _logger.warning("drain timed out with %d game(s) still active - exiting anyway", remaining)
    else:
        _logger.info("drain complete - every game finished naturally")

    run_task.cancel()
    if heartbeat is not None:
        heartbeat[0].cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await run_task


def main() -> None:  # pragma: no cover
    # The only place in the server package that configures logging output -
    # every other module (server/ws_server.py included) just calls
    # logging.getLogger(__name__) and trusts whoever runs the process to
    # have set this up, rather than each reaching for its own handler.
    configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
