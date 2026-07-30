"""Standalone API Gateway service - the one REST entry point in this
project's otherwise all-WebSocket wire protocol, fronting the PLAY/
matchmaking-request path and, as of this pass, authentication and room
create/join/cancel too (see Server_Design.md's own "REST for login/rooms/
history/matchmaking-request, WebSocket for live game commands" split,
docs/server-scaling-design branch). History stays on the websocket for
now - PLAY, Login (authentication only - see POST /login's own docstring
for the one piece of LoginMessage's three branches this narrower endpoint
doesn't replicate), and Rooms move here so far.

No session/token anywhere in this module - the same "just for
presentation" trust level server/accounts.py's own docstring already
states for login: once POST /login accepts a username, every later call
(POST /play, POST /rooms/..., and the IDENTIFY websocket message a client
sends afterward - see client/network_client.py's own api_gateway_port-
gated login()) is just told which already-authenticated username is
asking, the same way the all-websocket flow already worked before this
pass. Reuses this project's existing pieces directly rather than
re-deriving the decisions server/router.py's CommandRouter used to make
in-process: server/redis/busy_set.py's BusySet, server/redis/matchmaking.py's
RedisMatchmakingQueue, server/redis/active_game_index.py's ActiveGameIndex,
server/redis/rooms.py's RedisRoomRegistry (already the cross-process shared
state a standalone service needs), and server/postgres/accounts.py's
PostgresUserStore/PostgresRatingStore for authentication and the rating
lookup. This service always needs Postgres, never SQLite - a separate
container has no access to game-server's own SQLite file, and there's no
meaningful bare-metal mode for a networked REST gateway the way there is
for game-server itself.

The busy/already-queued checks and the rating lookup stay synchronous here
(an immediate REST response needs them), but what actually allocates a
Game Server Shard does not, for both PLAY and Rooms alike - per
Server_Design.md §6.2/§4:
    - PLAY: this handler publishes matchmaking.requested;
      services/matchmaker/main.py's own _on_matchmaking_requested is what
      calls queue.enqueue, and eventually publishes match.found for
      services/game_allocator/main.py to allocate a shard + lease.
    - Rooms: handle_join_room publishes room.opponent_joined the instant
      the second seat fills (the room-flow's own equivalent of
      match.found) - services/game_allocator/main.py subscribes to both
      events and allocates a shard + lease either way (see its own
      docstring for the one difference: a room's game_id is its own
      room_id, not a freshly minted one).
This means "accepted" can be returned microseconds before the underlying
enqueue/allocation actually lands - the documented, accepted cost of the
decoupling (see services/matchmaker/main.py's own docstring for the
harmless re-enqueue case this opens up), not a race this module tries to
close.

Every response here mirrors the matching wire ack's shape (LoginAckMessage/
PlayAckMessage/CreateRoomAckMessage/JoinRoomAckMessage/CancelRoomAckMessage)
but is a plain JSON REST response, not one of protocol/registry.py's
registered wire messages - this is a new REST surface, not the WebSocket
wire protocol.

This service also subscribes to game.finished (the same event
services/persistence_worker/main.py already consumes for durable history)
purely to clean up RedisRoomRegistry's own Redis keys once a room's game
ends - see that module's own docstring for why it needs this (GameLoop
never sees this registry, only the in-process one), and for the one known
gap (a crashed game's cleanup is skipped, same as its history).
"""

import asyncio
import json
import logging
import os
from typing import Dict, Optional

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from protocol.types import Reason, Role
from server.accounts import InvalidCredentialsError
from server.logging_config import configure_logging, room_id_ctx, username_ctx
from server.postgres.accounts import (
    PostgresAccountsDatabase,
    PostgresRatingStore,
    PostgresUserStore,
    open_postgres_accounts_database,
)
from server.redis.active_game_index import ActiveGameIndex
from server.redis.busy_set import BusySet
from server.redis.leaderboard import Leaderboard
from server.redis.matchmaking import RedisMatchmakingQueue
from server.redis.presence import Presence
from server.redis.room_shard_index import RoomShardIndex
from server.redis.rooms import RedisRoomRegistry
from server.rooms import RoomError

_logger = logging.getLogger(__name__)

routes = web.RouteTableDef()

# Server_Design.md §9's own "connection count and request rate per Gateway
# pod" - request rate half, per route (see _count_requests below); this
# service has no persistent "connection" of its own to count (each request
# is a stateless REST call, unlike services/ws_gateway/main.py's own
# long-lived relay - see its own kfchess_ws_gateway_connections gauge).
_REQUEST_COUNTER = Counter("kfchess_api_requests_total", "Total API Gateway requests", ["route"])


# Counts every ordinary route below by its own canonical path pattern
# (e.g. "/rooms/{room_id}/join", never the raw request.path with a real
# room_id in it - unbounded label cardinality would otherwise turn every
# distinct room into its own Prometheus timeseries forever). Excludes the
# observability routes themselves (/healthz//readyz//metrics) - polled far
# more often than real traffic and not meaningfully "an API request" in
# the same sense.
_OBSERVABILITY_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})


@web.middleware
async def _count_requests(request: web.Request, handler):
    response = await handler(request)
    if request.path not in _OBSERVABILITY_PATHS:
        resource = request.match_info.route.resource
        route = resource.canonical if resource is not None else request.path
        _REQUEST_COUNTER.labels(route=route).inc()
    return response


# Server_Design.md §9's own health/readiness probes - liveness always 200
# (this handler running at all is the signal), readiness actually checks
# this service's three real dependencies (Redis/Postgres/NATS) via
# dedicated clients, the same synchronous-check shape server/main.py's own
# _build_readiness_checks uses for the bare-metal shard, just inline here
# since this service already has an aiohttp app to hang routes on instead
# of needing server/observability_server.py's own second HTTP server.
@routes.get("/healthz")
async def handle_healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


# Off the event loop entirely, via the default thread-pool executor - same
# reasoning as handle_login's own PBKDF2 call above: Redis/Postgres checks
# here are real (if brief) blocking I/O, and aiohttp runs single-threaded,
# so calling either directly would freeze every other concurrent request
# this service is serving - including /healthz itself - for as long as an
# unreachable dependency takes to time out. A real docker-compose run
# (Redis stopped mid-check) is what actually surfaced this, not a guess:
# /healthz measured 7+ seconds to answer, blocked behind a concurrent
# /readyz call's own un-timed-out socket connect, before this fix.
def _check_redis_and_postgres(redis_url: str, database_url: str, replica_database_url: Optional[str]) -> Dict[str, bool]:
    import psycopg
    import redis as redis_lib

    results = {}

    try:
        # Explicit, short timeouts - redis-py's own default is *no* timeout
        # at all, which would hang this check instead of failing it fast.
        redis_client = redis_lib.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        results["redis"] = bool(redis_client.ping())
    except Exception:
        results["redis"] = False

    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
        results["postgres"] = True
    except Exception:
        results["postgres"] = False

    # Only checked when actually configured (see _build_rating_store) -
    # every existing deployment with no DATABASE_URL_REPLICA at all keeps
    # today's two-dependency readiness check unchanged.
    if replica_database_url is not None:
        try:
            with psycopg.connect(replica_database_url, connect_timeout=2) as connection:
                connection.execute("SELECT 1")
            results["postgres_replica"] = True
        except Exception:
            results["postgres_replica"] = False

    return results


@routes.get("/readyz")
async def handle_readyz(request: web.Request) -> web.Response:
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None,
        _check_redis_and_postgres,
        request.app["redis_url"],
        request.app["database_url"],
        os.environ.get("DATABASE_URL_REPLICA"),
    )

    nats_connection = request.app.get("nats_connection")
    results["nats"] = bool(nats_connection.is_connected) if nats_connection is not None else False

    return web.json_response(results, status=200 if all(results.values()) else 503)


@routes.get("/metrics")
async def handle_metrics(request: web.Request) -> web.Response:
    # Not content_type=CONTENT_TYPE_LATEST - aiohttp's own Response
    # rejects a content_type string that already carries a charset (which
    # CONTENT_TYPE_LATEST does, "text/plain; version=1.0.0; charset=utf-8"),
    # since it manages charset separately itself. Setting the raw header
    # directly sidesteps that entirely - verified against a real running
    # container, which is what actually caught this (every unit/integration
    # test calls handle_metrics as a plain coroutine, never through
    # aiohttp's own Response validation).
    return web.Response(body=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})


# Authentication only - see this module's own docstring for why rooms/
# history stay on the websocket for now. Unlike LoginMessage's own
# decide_login (server/router.py), this never replicates the "a room
# survived a server restart" branch: that branch needs "is the other
# participant currently connected," a fact that stops being well-defined
# once login itself is a one-shot REST call instead of the start of a
# persistent connection (see server/interfaces.py's ActiveGameIndexProtocol
# docstring). It *does* replicate "reconnect into an already-live
# GameSession" - via active_game_index, the cross-process view of exactly
# that fact - so a REST-based client still learns reconnected/color
# up front, the same as an all-websocket client already does; the actual
# reconnect (GameSession.mark_reconnected) still happens in-process, once
# the client follows up with an IDENTIFY message over its websocket (see
# server/ws_server.py's _handle_identify, server/router.py's
# CommandRouter.decide_identify).
@routes.post("/login")
async def handle_login(request: web.Request) -> web.Response:
    body = await request.json()
    username = body["username"]
    username_ctx.set(username)
    password = body["password"]

    user_store: PostgresUserStore = request.app["user_store"]
    rating_store: PostgresRatingStore = request.app["rating_store"]
    active_game_index: ActiveGameIndex = request.app["active_game_index"]

    # Off the event loop entirely, via the default thread-pool executor -
    # same reasoning as server/ws_server.py's own _handle_login: PBKDF2 is
    # real, non-trivial CPU work that would otherwise freeze every other
    # concurrent request this shared aiohttp event loop is serving.
    loop = asyncio.get_event_loop()
    try:
        account = await loop.run_in_executor(None, user_store.login, username, password)
    except InvalidCredentialsError:
        return web.json_response({"accepted": False, "reason": Reason.WRONG_PASSWORD.value})

    rating = rating_store.rating_for(account.username)

    location = active_game_index.get(account.username)
    if location is not None:
        return web.json_response(
            {"accepted": True, "username": account.username, "rating": rating, "reconnected": True, "color": location.seat}
        )

    return web.json_response({"accepted": True, "username": account.username, "rating": rating})


# Same busy-check server/router.py's CommandRouter._busy_reason (by way of
# server/participant.py's participant_state) makes in-process, minus the
# spectator case - see server/redis/busy_set.py's own docstring on why
# that's a deliberate, flagged relaxation, not a bug nobody noticed. Shared
# by every route below (play/create/join) the same way _busy_reason is
# shared by decide_play/decide_create_room/decide_join_room there - one
# username can only ever be committed to one thing (queued OR in a room)
# across both tracks together.
def _busy_reason(username: str, busy_set: BusySet, matchmaking: RedisMatchmakingQueue) -> Optional[str]:
    if busy_set.contains(username):
        return Reason.ALREADY_IN_GAME.value
    if matchmaking.is_waiting(username):
        return Reason.ALREADY_QUEUED.value
    return None


@routes.post("/play")
async def handle_play(request: web.Request) -> web.Response:
    body = await request.json()
    username = body["username"]
    username_ctx.set(username)

    busy_set: BusySet = request.app["busy_set"]
    matchmaking: RedisMatchmakingQueue = request.app["matchmaking"]
    rating_store: PostgresRatingStore = request.app["rating_store"]

    reason = _busy_reason(username, busy_set, matchmaking)
    if reason is not None:
        return web.json_response({"accepted": False, "reason": reason})

    rating = rating_store.rating_for(username)
    nats_connection = request.app["nats_connection"]
    payload = {"username": username, "rating": rating}
    await nats_connection.publish("matchmaking.requested", json.dumps(payload).encode("utf-8"))
    _logger.info("'%s' requested a match (rating %d)", username, rating)
    return web.json_response({"accepted": True, "reason": Reason.QUEUED.value})


@routes.post("/rooms")
async def handle_create_room(request: web.Request) -> web.Response:
    body = await request.json()
    username = body["username"]
    username_ctx.set(username)

    busy_set: BusySet = request.app["busy_set"]
    matchmaking: RedisMatchmakingQueue = request.app["matchmaking"]
    rooms: RedisRoomRegistry = request.app["rooms"]

    reason = _busy_reason(username, busy_set, matchmaking)
    if reason is not None:
        return web.json_response({"accepted": False, "reason": reason})

    try:
        room = rooms.create(username)
    except RoomError as error:
        return web.json_response({"accepted": False, "reason": str(error)})

    _logger.info("'%s' created room %s", username, room.room_id)
    return web.json_response({"accepted": True, "room_id": room.room_id})


# The one route that can also trigger shard allocation - see this module's
# own docstring on why "room.opponent_joined" plays the exact same role
# here that "match.found" plays for /play, published the instant the
# second seat fills (role == Role.OPPONENT), never for a spectator join.
# A spectator join needs no event and no shard lookup at all: rooms.join()
# above already recorded them in RedisRoomRegistry's own spectators set,
# and the room's game (if it exists yet) already has a shard - see
# server/router.py's decide_identify and services/ws_gateway/main.py's
# _resolve_shard, which both read that same durable state directly,
# exactly when they need it, instead of this route pushing a redundant
# copy of the same fact through NATS.
@routes.post("/rooms/{room_id}/join")
async def handle_join_room(request: web.Request) -> web.Response:
    room_id = request.match_info["room_id"]
    room_id_ctx.set(room_id)
    body = await request.json()
    username = body["username"]
    username_ctx.set(username)

    busy_set: BusySet = request.app["busy_set"]
    matchmaking: RedisMatchmakingQueue = request.app["matchmaking"]
    rooms: RedisRoomRegistry = request.app["rooms"]

    reason = _busy_reason(username, busy_set, matchmaking)
    if reason is not None:
        return web.json_response({"accepted": False, "reason": reason})

    try:
        room = rooms.join(room_id, username)
    except RoomError as error:
        return web.json_response({"accepted": False, "reason": str(error)})

    role = Role.OPPONENT if room.opponent == username else Role.SPECTATOR
    if role == Role.OPPONENT:
        nats_connection = request.app["nats_connection"]
        payload = {"room_id": room_id, "creator": room.creator, "opponent": room.opponent}
        await nats_connection.publish("room.opponent_joined", json.dumps(payload).encode("utf-8"))
        _logger.info("'%s' joined room %s as opponent - allocating a shard", username, room_id)

    return web.json_response({"accepted": True, "room_id": room_id, "role": role.value})


# No room_id in the path - matches CancelRoomMessage's own wire shape
# (server/rooms.py's RoomRegistry.cancel takes only a username: a room's
# creator can only ever be pending in one room at a time, so there's
# nothing a room_id would disambiguate here that room_for_username doesn't
# already resolve on its own).
@routes.post("/rooms/cancel")
async def handle_cancel_room(request: web.Request) -> web.Response:
    body = await request.json()
    username = body["username"]
    username_ctx.set(username)

    rooms: RedisRoomRegistry = request.app["rooms"]
    try:
        rooms.cancel(username)
    except RoomError as error:
        return web.json_response({"accepted": False, "reason": str(error)})

    _logger.info("'%s' cancelled their room", username)
    return web.json_response({"accepted": True})


# Server_Design.md §5's own Redis leaderboard (server/redis/leaderboard.py) -
# an incremental read off the same ZSET every rating change already keeps
# in sync (see server/main.py's own LeaderboardRatingStore, wrapped around
# whichever RatingRepository a shard is using), never a live `ORDER BY`
# over the accounts table.
@routes.get("/leaderboard")
async def handle_leaderboard(request: web.Request) -> web.Response:
    leaderboard: Leaderboard = request.app["leaderboard"]
    limit = int(request.query.get("limit", 10))
    entries = [{"username": username, "rating": rating} for username, rating in leaderboard.top(limit)]
    return web.json_response({"entries": entries})


# Server_Design.md §5's own presence/session directory (server/redis/presence.py) -
# read-only here; services/ws_gateway/main.py is what actually marks a
# username online/offline, since it's the process that actually terminates
# that username's socket in this deployment (see its own docstring).
@routes.get("/presence/{username}")
async def handle_presence(request: web.Request) -> web.Response:
    username = request.match_info["username"]
    presence: Presence = request.app["presence"]
    return web.json_response({"username": username, "online": presence.is_online(username)})


# Cleans up RedisRoomRegistry's own Redis keys, and the §4 room_id ->
# shard_address mapping (server/redis/room_shard_index.py's RoomShardIndex,
# written by services/game_allocator/main.py's own _allocate) once a room's
# game actually ends - see RedisRoomRegistry's own docstring on why this
# class needs an explicit game.finished subscription (unlike
# server/rooms.py's RoomRegistry, which GameLoop already closes directly,
# in-process, on the very same object). room_id is None for a PLAY match's
# game.finished - nothing to clean up here in that case.
async def _on_game_finished(rooms: RedisRoomRegistry, room_shard_index: RoomShardIndex, msg) -> None:
    payload = json.loads(msg.data)
    room_id = payload.get("room_id")
    if room_id is not None:
        room_id_ctx.set(room_id)
        rooms.close(room_id)
        room_shard_index.remove(room_id)


async def _on_startup(app: web.Application) -> None:
    import nats

    nats_url = os.environ["NATS_URL"]
    nats_connection = await nats.connect(nats_url)
    app["nats_connection"] = nats_connection

    rooms: RedisRoomRegistry = app["rooms"]
    room_shard_index: RoomShardIndex = app["room_shard_index"]

    async def _on_message(msg) -> None:
        await _on_game_finished(rooms, room_shard_index, msg)

    app["game_finished_sub"] = await nats_connection.subscribe("game.finished", cb=_on_message)


async def _on_cleanup(app: web.Application) -> None:
    await app["game_finished_sub"].unsubscribe()
    await app["nats_connection"].close()


# Prefers a replica-backed PostgresRatingStore's read but falls back to the
# primary's when the replica doesn't have the row (yet) - a real race, not
# a theoretical one: this project's own docker-compose verification of this
# pass hit it on the very first try, a brand-new account's first-ever
# rating_for running before the replica had streamed the INSERT
# handle_login's own login() call had just committed to the primary,
# moments earlier, in the same request. Falling back to the primary on
# that specific case keeps the common case (a returning user, or any read
# more than a few ms after its own registration) on the fast, load-shedding
# replica path, while a brand-new account's own very first read - the one
# case guaranteed to race - still gets the right, definitely-not-yet-stale
# answer instead of a 500.
#
# update_rating is never called through this - api_gateway never writes
# ratings at all (see this module's own docstring) - so it's deliberately
# not implemented here, rather than silently writing to a replica that
# would reject it outright anyway.
class _ReplicaWithPrimaryFallbackRatingStore:
    def __init__(self, replica_store: PostgresRatingStore, primary_store: PostgresRatingStore):
        self._replica_store = replica_store
        self._primary_store = primary_store

    def rating_for(self, username: str) -> int:
        rating = self._replica_store.rating_for_or_none(username)
        return rating if rating is not None else self._primary_store.rating_for(username)


# DATABASE_URL_REPLICA unset (the default) keeps rating_store reading from
# the same primary accounts_database everything else here uses - today's
# behavior, unchanged. Set (see docker-compose.yml's own postgres-replica
# service, a genuine streaming standby - Server_Design.md §5's own
# "PostgreSQL/MySQL, primary + read replicas"), this service's own two
# rating_for call sites (handle_login's display, handle_play's matchmaking
# lookup - both read-only, both tolerant of a few hundred ms of replica
# lag) read from the replica instead (with the primary fallback above),
# leaving every write (and every other read this service does) on the
# primary. Deliberately never wired into server/main.py's own shard-side
# rating_store: GameSession.finalize_ratings_if_game_over reads a rating
# and writes its own update in the same operation, which needs the
# primary's strong consistency, not a possibly-stale replica read feeding a
# wrong ELO calculation - see this function's own accounts_database, still
# the only store passed to PostgresUserStore (login/register also needs
# read-then-conditionally-write consistency, for the same reason).
def _build_rating_store(accounts_database) -> PostgresRatingStore:
    replica_url = os.environ.get("DATABASE_URL_REPLICA")
    primary_rating_store = PostgresRatingStore(accounts_database)
    if replica_url is None:
        return primary_rating_store

    # Not open_postgres_accounts_database - its own CREATE TABLE IF NOT
    # EXISTS is a write, and a standby physically rejects every write
    # (including DDL), even one that would be a no-op. The primary's own
    # accounts_database (already opened above, in build_app) already
    # created this table if needed - streaming replication carries schema
    # changes the same as row changes, so there's nothing left for this
    # connection to create.
    import psycopg

    replica_connection = psycopg.connect(replica_url, autocommit=False)
    replica_rating_store = PostgresRatingStore(PostgresAccountsDatabase(connection=replica_connection))
    return _ReplicaWithPrimaryFallbackRatingStore(replica_rating_store, primary_rating_store)


def build_app() -> web.Application:
    database_url = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]

    accounts_database = open_postgres_accounts_database(database_url)
    busy_set = BusySet(redis_url)

    app = web.Application(middlewares=[_count_requests])
    app["redis_url"] = redis_url
    app["database_url"] = database_url
    app["user_store"] = PostgresUserStore(accounts_database)
    app["rating_store"] = _build_rating_store(accounts_database)
    app["matchmaking"] = RedisMatchmakingQueue(redis_url)
    app["busy_set"] = busy_set
    app["active_game_index"] = ActiveGameIndex(redis_url)
    app["rooms"] = RedisRoomRegistry(redis_url, busy_set=busy_set)
    app["room_shard_index"] = RoomShardIndex(redis_url)
    app["leaderboard"] = Leaderboard(redis_url)
    app["presence"] = Presence(redis_url)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.add_routes(routes)
    return app


def main() -> None:  # pragma: no cover
    configure_logging()
    port = int(os.environ.get("API_GATEWAY_PORT", 8080))
    web.run_app(build_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
