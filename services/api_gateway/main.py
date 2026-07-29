"""Standalone API Gateway service - the one REST entry point in this
project's otherwise all-WebSocket wire protocol, fronting exactly the
PLAY/matchmaking-request path (see Server_Design.md's own "REST for
login/rooms/history/matchmaking-request, WebSocket for live game commands"
split, docs/server-scaling-design branch). Login/rooms/history stay on
the websocket, unchanged - only PLAY moves here, the narrower scope
actually approved for this pass.

One route: POST /play, body {"username": str} - no session/token, the
same "just for presentation" trust level server/accounts.py's own
docstring already states for login: the client already logged in over the
websocket; this call is just told which already-authenticated username is
asking. Reuses this project's existing pieces directly rather than
re-deriving the decision server/router.py's CommandRouter.decide_play used
to make in-process: server/redis/busy_set.py's BusySet and
server/redis/matchmaking.py's RedisMatchmakingQueue (already the
cross-process shared state a standalone service needs), and
server/postgres/accounts.py's PostgresRatingStore for the rating lookup.
This service always needs Postgres, never SQLite - a separate container
has no access to game-server's own SQLite file, and there's no meaningful
bare-metal mode for a networked REST gateway the way there is for
game-server itself.

The busy/already-queued checks and the rating lookup stay synchronous here
(an immediate REST response needs them), but the actual enqueue does not:
per Server_Design.md §6.2 ("API Gateway publishes a matchmaking request
onto the NATS control plane. Matchmaker sees every waiting player
globally"), this handler publishes matchmaking.requested and
services/matchmaker/main.py's own _on_matchmaking_requested is what calls
queue.enqueue. This means "accepted" can be returned microseconds before
the enqueue actually lands - the documented, accepted cost of the
decoupling (see services/matchmaker/main.py's own docstring for the harmless
re-enqueue case this opens up), not a race this module tries to close.

The response mirrors PlayAckMessage's shape ({"accepted": bool, "reason":
str}) but is a plain JSON REST response, not one of protocol/registry.py's
registered wire messages - this is a new REST surface, not the WebSocket
wire protocol.
"""

import json
import logging
import os

from aiohttp import web

from protocol.types import Reason
from server.postgres.accounts import PostgresRatingStore, open_postgres_accounts_database
from server.redis.busy_set import BusySet
from server.redis.matchmaking import RedisMatchmakingQueue

_logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


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
    app["rating_store"] = PostgresRatingStore(accounts_database)
    app["matchmaking"] = RedisMatchmakingQueue(redis_url)
    app["busy_set"] = BusySet(redis_url)
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
