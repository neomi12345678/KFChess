"""Standalone API Gateway service - the one REST entry point in this
project's otherwise all-WebSocket wire protocol, fronting the PLAY/
matchmaking-request path and, as of this pass, authentication too (see
Server_Design.md's own "REST for login/rooms/history/matchmaking-request,
WebSocket for live game commands" split, docs/server-scaling-design
branch). Rooms/history stay on the websocket for now - only PLAY and
Login (authentication only - see POST /login's own docstring for the one
piece of LoginMessage's three branches this narrower endpoint doesn't
replicate) move here so far.

No session/token anywhere in this module - the same "just for
presentation" trust level server/accounts.py's own docstring already
states for login: once POST /login accepts a username, every later call
(POST /play, and the IDENTIFY websocket message a client sends afterward -
see client/network_client.py's own api_gateway_port-gated login()) is just
told which already-authenticated username is asking, the same way the
all-websocket flow already worked before this pass. Reuses this project's
existing pieces directly rather than re-deriving the decisions
server/router.py's CommandRouter used to make in-process:
server/redis/busy_set.py's BusySet, server/redis/matchmaking.py's
RedisMatchmakingQueue, server/redis/active_game_index.py's ActiveGameIndex
(already the cross-process shared state a standalone service needs), and
server/postgres/accounts.py's PostgresUserStore/PostgresRatingStore for
authentication and the rating lookup. This service always needs Postgres,
never SQLite - a separate container has no access to game-server's own
SQLite file, and there's no meaningful bare-metal mode for a networked
REST gateway the way there is for game-server itself.

The busy/already-queued checks and the rating lookup stay synchronous here
(an immediate REST response needs them), but the actual matchmaking
enqueue does not: per Server_Design.md §6.2 ("API Gateway publishes a
matchmaking request onto the NATS control plane. Matchmaker sees every
waiting player globally"), handle_play publishes matchmaking.requested and
services/matchmaker/main.py's own _on_matchmaking_requested is what calls
queue.enqueue. This means "accepted" can be returned microseconds before
the enqueue actually lands - the documented, accepted cost of the
decoupling (see services/matchmaker/main.py's own docstring for the
harmless re-enqueue case this opens up), not a race this module tries to
close.

Every response here mirrors the matching wire ack's shape (LoginAckMessage/
PlayAckMessage) but is a plain JSON REST response, not one of
protocol/registry.py's registered wire messages - this is a new REST
surface, not the WebSocket wire protocol.
"""

import asyncio
import json
import logging
import os

from aiohttp import web

from protocol.types import Reason
from server.accounts import InvalidCredentialsError
from server.postgres.accounts import (
    PostgresRatingStore,
    PostgresUserStore,
    open_postgres_accounts_database,
)
from server.redis.active_game_index import ActiveGameIndex
from server.redis.busy_set import BusySet
from server.redis.matchmaking import RedisMatchmakingQueue

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


@routes.post("/play")
async def handle_play(request: web.Request) -> web.Response:
    body = await request.json()
    username = body["username"]

    busy_set: BusySet = request.app["busy_set"]
    matchmaking: RedisMatchmakingQueue = request.app["matchmaking"]
    rating_store: PostgresRatingStore = request.app["rating_store"]

    # Same busy-check server/participant.py's participant_state makes
    # in-process, minus the spectator case - see server/redis/busy_set.py's
    # own docstring on why that's a deliberate, flagged relaxation, not a
    # bug nobody noticed.
    if busy_set.contains(username):
        return web.json_response({"accepted": False, "reason": Reason.ALREADY_IN_GAME.value})
    if matchmaking.is_waiting(username):
        return web.json_response({"accepted": False, "reason": Reason.ALREADY_QUEUED.value})

    rating = rating_store.rating_for(username)
    nats_connection = request.app["nats_connection"]
    payload = {"username": username, "rating": rating}
    await nats_connection.publish("matchmaking.requested", json.dumps(payload).encode("utf-8"))
    _logger.info("'%s' requested a match (rating %d)", username, rating)
    return web.json_response({"accepted": True, "reason": Reason.QUEUED.value})


async def _on_startup(app: web.Application) -> None:
    import nats

    nats_url = os.environ["NATS_URL"]
    app["nats_connection"] = await nats.connect(nats_url)


async def _on_cleanup(app: web.Application) -> None:
    await app["nats_connection"].close()


def build_app() -> web.Application:
    database_url = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]

    accounts_database = open_postgres_accounts_database(database_url)

    app = web.Application()
    app["user_store"] = PostgresUserStore(accounts_database)
    app["rating_store"] = PostgresRatingStore(accounts_database)
    app["matchmaking"] = RedisMatchmakingQueue(redis_url)
    app["busy_set"] = BusySet(redis_url)
    app["active_game_index"] = ActiveGameIndex(redis_url)
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
