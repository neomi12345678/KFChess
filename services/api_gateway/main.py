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
from typing import Optional

from aiohttp import web

from protocol.types import Reason, Role
from server.accounts import InvalidCredentialsError
from server.postgres.accounts import (
    PostgresRatingStore,
    PostgresUserStore,
    open_postgres_accounts_database,
)
from server.redis.active_game_index import ActiveGameIndex
from server.redis.busy_set import BusySet
from server.redis.matchmaking import RedisMatchmakingQueue
from server.redis.room_shard_index import RoomShardIndex
from server.redis.rooms import RedisRoomRegistry
from server.rooms import RoomError

_logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


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
    body = await request.json()
    username = body["username"]

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

    rooms: RedisRoomRegistry = request.app["rooms"]
    try:
        rooms.cancel(username)
    except RoomError as error:
        return web.json_response({"accepted": False, "reason": str(error)})

    _logger.info("'%s' cancelled their room", username)
    return web.json_response({"accepted": True})


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


def build_app() -> web.Application:
    database_url = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]

    accounts_database = open_postgres_accounts_database(database_url)
    busy_set = BusySet(redis_url)

    app = web.Application()
    app["user_store"] = PostgresUserStore(accounts_database)
    app["rating_store"] = PostgresRatingStore(accounts_database)
    app["matchmaking"] = RedisMatchmakingQueue(redis_url)
    app["busy_set"] = busy_set
    app["active_game_index"] = ActiveGameIndex(redis_url)
    app["rooms"] = RedisRoomRegistry(redis_url, busy_set=busy_set)
    app["room_shard_index"] = RoomShardIndex(redis_url)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.add_routes(routes)
    return app


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    port = int(os.environ.get("API_GATEWAY_PORT", 8080))
    web.run_app(build_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
