"""Standalone WS Gateway service - the "WS Gateway" role from
Server_Design.md §3/§11 (docs/server-scaling-design branch): stateless,
no game logic, a pure relay between a public client websocket and
whichever Game Server Shard actually owns that client's live game.

No new protocol between this and a Shard - a Shard is just
server/ws_server.py's existing GameServer, and this service connects to
one exactly the way any other client would: send IdentifyMessage
(server/router.py's CommandRouter.decide_identify already does everything
a shard-side attach needs - register the connection, reconnect a
disconnected seat if any), wait for IdentifyAckMessage, then relay every
further raw frame in both directions unmodified. This is what
Server_Design.md §3 means by "stateless... pub/sub bridge only" - this
service never decodes a MOVE/JUMP or a snapshot broadcast to *act* on it,
only the two lobby messages needed to know when the relay itself should
start or give up.

A client using this service needs no code changes at all (see
client/network_client.py's own docstring on why it's transparent) - only
a deployment pointed at this service's own host:port instead of straight
at a Shard's.

Resolving *which* shard to relay to has three cases, all driven by existing
cross-process state rather than anything new invented here:

    1. The username already has a live game as a seated player (reconnect,
       or already allocated by the time this connection arrives) - answered
       directly by server/redis/active_game_index.py's ActiveGameIndex.get().
    2. The username is an existing room's spectator (see
       services/api_gateway/main.py's handle_join_room, which only ever
       records this in RedisRoomRegistry - no event of its own) - answered
       by server/redis/rooms.py's RedisRoomRegistry.room_for_username()
       plus server/redis/room_shard_index.py's RoomShardIndex.get(), the
       Server_Design.md §4 `room_id -> worker` mapping itself. No waiting:
       the room's game already exists by the time anyone can join it as a
       spectator, so there's nothing left to be allocated.
    3. The username is still waiting on a fresh allocation (just called
       POST /play, or just filled a room's opponent seat) - this service
       waits on the same game.allocated event services/game_allocator/main.py
       already publishes (see server/game_loop.py's own
       start_game_allocation_relay for the Shard-side sibling of this same
       subscription), or gives up on matchmaking.timeout. One shared NATS
       subscription per process (not per connection) dispatches to
       whichever connection is currently waiting for that username, the
       same efficiency server/game_loop.py's own relay methods already have
       - not a separate subscription per client.

While a client is still waiting on case 3 above (no shard to relay to yet),
it also gets every matchmaking.status "still searching" heartbeat relayed
straight through (see _StatusRelay) - the same periodic
MatchmakingStatusMessage a bare-metal GameServer already sends directly
(server/game_loop.py's own _advance_matchmaking), now arriving from the
standalone Matchmaker service instead over the same one-shared-subscription
shape as game.allocated/matchmaking.timeout above. A spectator (case 2)
never reaches this wait at all - nothing to be "still searching" for.
"""

import asyncio
import contextlib
import json
import logging
import os
from typing import Dict, Optional

import websockets
from prometheus_client import Gauge

from protocol.game_messages import ErrorMessage
from protocol.lobby_messages import (
    IdentifyAckMessage,
    IdentifyMessage,
    MatchmakingStatusMessage,
    MatchmakingTimeoutMessage,
)
from protocol.registry import decode_json_message, encode_json_message
from protocol.types import PORT as SHARD_PORT
from protocol.types import WS_GATEWAY_PORT
from server.logging_config import configure_logging, username_ctx
from server.observability_server import start_observability_server
from server.redis.active_game_index import ActiveGameIndex
from server.redis.presence import Presence
from server.redis.room_shard_index import RoomShardIndex
from server.redis.rooms import RedisRoomRegistry
from server.server_config import MATCHMAKING_TIMEOUT_MS

_logger = logging.getLogger(__name__)

# Server_Design.md §9's own "connection count... per Gateway pod" - every
# currently relayed (or still-resolving) client, from the moment
# _handle_client accepts it to the moment it disconnects.
_CONNECTIONS_GAUGE = Gauge("kfchess_ws_gateway_connections", "Currently connected clients")


# One shared table per process - {username: Future[shard_address or None]}
# - so a single NATS subscription (see _subscribe_allocation_events) can
# resolve whichever connection is currently waiting for that username's
# shard, the same "one subscription, many concurrent waiters" shape
# server/game_loop.py's own start_matchmaking_relay/
# start_game_allocation_relay already use for live connections instead.
class _AllocationWaiters:
    def __init__(self):
        self._pending: Dict[str, "asyncio.Future[Optional[str]]"] = {}

    def wait_for(self, username: str) -> "asyncio.Future[Optional[str]]":
        future = asyncio.get_event_loop().create_future()
        self._pending[username] = future
        return future

    # None means "gave up" (matchmaking.timeout) - resolved the same way
    # for either event, so _resolve_shard below has one place to interpret it.
    def resolve(self, username: str, shard_address: Optional[str]) -> None:
        future = self._pending.pop(username, None)
        if future is not None and not future.done():
            future.set_result(shard_address)


# One shared table per process - {username: client_ws} - so the same
# single matchmaking.status subscription below can push each "still
# searching" heartbeat straight to whichever connection is currently
# waiting for that username, mirroring _AllocationWaiters' own "one
# subscription, many concurrent waiters" shape. A plain dict rather than
# another Future-based waiter: unlike game.allocated/matchmaking.timeout,
# a username can receive many of these before the wait ends, so there's
# nothing here to ever resolve once and discard.
class _StatusRelay:
    def __init__(self):
        self._waiting: Dict[str, object] = {}

    def register(self, username: str, client_ws) -> None:
        self._waiting[username] = client_ws

    def unregister(self, username: str) -> None:
        self._waiting.pop(username, None)

    def get(self, username: str):
        return self._waiting.get(username)


async def _subscribe_matchmaking_events(
    nats_connection, waiters: _AllocationWaiters, status_relay: _StatusRelay
) -> None:
    async def _on_allocated(msg) -> None:
        payload = json.loads(msg.data)
        for username in (payload["white_username"], payload["black_username"]):
            waiters.resolve(username, payload["shard_address"])

    async def _on_timeout(msg) -> None:
        payload = json.loads(msg.data)
        waiters.resolve(payload["username"], None)

    async def _on_status(msg) -> None:
        payload = json.loads(msg.data)
        client_ws = status_relay.get(payload["username"])
        if client_ws is None:
            return
        message = encode_json_message(MatchmakingStatusMessage(seconds_remaining=payload["seconds_remaining"]))
        with contextlib.suppress(websockets.exceptions.ConnectionClosed):
            await client_ws.send(message)

    await nats_connection.subscribe("game.allocated", cb=_on_allocated)
    await nats_connection.subscribe("matchmaking.timeout", cb=_on_timeout)
    await nats_connection.subscribe("matchmaking.status", cb=_on_status)


# None means "give up" - the caller sends MatchmakingTimeoutMessage and
# closes rather than ever attempting to relay with no shard to relay to.
# The outer wait_for bound (MATCHMAKING_TIMEOUT_MS, server/server_config.py
# - not a new constant) is a safety net for the case nothing ever arrives,
# same reasoning client/network_client.py's own _wait_for_type already has
# for every blocking wire wait in this project.
async def _resolve_shard(
    username: str,
    active_game_index: ActiveGameIndex,
    rooms: RedisRoomRegistry,
    room_shard_index: RoomShardIndex,
    waiters: _AllocationWaiters,
) -> Optional[str]:
    location = active_game_index.get(username)
    if location is not None:
        return location.shard_address

    # A spectator of an already-existing room's game - see this module's
    # own docstring, case 2. Synchronous, no waiting: by the time a room
    # shows up here as a room_for_username hit with this username in its
    # spectators, the room's game already exists (that's the only way a
    # join ever becomes a spectator join rather than an opponent one).
    room = rooms.room_for_username(username)
    if room is not None and username in room.spectators:
        return room_shard_index.get(room.room_id)

    future = waiters.wait_for(username)
    try:
        return await asyncio.wait_for(future, timeout=MATCHMAKING_TIMEOUT_MS / 1000)
    except asyncio.TimeoutError:
        return None


async def _pump(source, destination) -> None:
    async for message in source:
        await destination.send(message)


# Server_Design.md §9's own "affected clients get an error" - the ws_gateway
# side of the same story server/game_loop.py's own _fail_game already
# covers for a crash *inside* a still-running shard process (see its own
# ErrorMessage(message="internal_error") send). This covers the other half:
# the shard process itself disappearing (killed pod, network partition)
# out from under an in-progress relay - services/game_allocator/main.py's
# own recovery sweep notices this too, eventually (polling
# server/redis/shard_registry.py's heartbeat TTL), but this notices the
# instant the actual TCP connection to the shard drops, which is always at
# least as fast and doesn't depend on sweep timing. asyncio.wait with
# FIRST_EXCEPTION (not asyncio.gather) is what makes this distinguishable:
# gather would raise the first exception but leave the other pump running
# in the background rather than telling us which direction actually failed.
async def _relay(client_ws, shard_address: str, shard_port: int, username: str) -> None:
    uri = f"ws://{shard_address}:{shard_port}"
    async with websockets.connect(uri) as internal_ws:
        await internal_ws.send(encode_json_message(IdentifyMessage(username=username)))

        # Forwards everything the shard sends in response to this internal
        # IDENTIFY - including the IdentifyAckMessage itself - straight to
        # the public client, same as ordinary pump content below; only
        # *watches* for the ack to know when the handshake is done and the
        # two-way pump should start. This client is a real one
        # (client/network_client.py's own login()) that explicitly sends
        # IdentifyMessage and then waits for IdentifyAckMessage back - this
        # module's own docstring promises "no code changes at all" for that
        # client, which only holds if the ack (and anything else interleaved
        # before it, though nothing else is published to a freshly-identified
        # shard connection this early) actually reaches it rather than being
        # silently swallowed here.
        async for raw in internal_ws:
            await client_ws.send(raw)
            if isinstance(decode_json_message(raw), IdentifyAckMessage):
                break

        client_to_shard = asyncio.ensure_future(_pump(client_ws, internal_ws))
        shard_to_client = asyncio.ensure_future(_pump(internal_ws, client_ws))
        done, pending = await asyncio.wait({client_to_shard, shard_to_client}, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()

        # shard_to_client reads from internal_ws (the shard) and writes to
        # client_ws - it's the one that fails when the *shard* connection
        # drops, as opposed to client_to_shard failing because the client
        # itself left. Only the former is a surprise worth explaining.
        if shard_to_client in done and shard_to_client.exception() is not None:
            with contextlib.suppress(websockets.exceptions.ConnectionClosed):
                await client_ws.send(encode_json_message(ErrorMessage(message="shard_unavailable")))

        for task in done:
            error = task.exception()
            if error is not None:
                raise error


async def _handle_client(
    active_game_index: ActiveGameIndex,
    rooms: RedisRoomRegistry,
    room_shard_index: RoomShardIndex,
    waiters: _AllocationWaiters,
    status_relay: _StatusRelay,
    presence: Presence,
    shard_port: int,
    client_ws,
) -> None:
    # _CONNECTIONS_GAUGE covers this client's whole lifetime - accepted
    # through disconnected - not just its relay phase, so it counts a
    # still-resolving (waiting on allocation) client too.
    _CONNECTIONS_GAUGE.inc()
    try:
        await _handle_client_inner(
            active_game_index, rooms, room_shard_index, waiters, status_relay, presence, shard_port, client_ws
        )
    finally:
        _CONNECTIONS_GAUGE.dec()


async def _handle_client_inner(
    active_game_index: ActiveGameIndex,
    rooms: RedisRoomRegistry,
    room_shard_index: RoomShardIndex,
    waiters: _AllocationWaiters,
    status_relay: _StatusRelay,
    presence: Presence,
    shard_port: int,
    client_ws,
) -> None:
    try:
        raw = await client_ws.recv()
    except websockets.exceptions.ConnectionClosed:
        return

    decoded = decode_json_message(raw)
    if not isinstance(decoded, IdentifyMessage):
        await client_ws.send(encode_json_message(ErrorMessage(message="identify_required")))
        return

    username = decoded.username
    username_ctx.set(username)
    # Server_Design.md §5's own presence/session directory - this service is
    # the one that actually terminates the client's socket in the
    # Dockerized deployment (see this module's own docstring), so it's the
    # natural place to mark a username online/offline, mirroring
    # _CONNECTIONS_GAUGE's own whole-lifetime scope just above.
    presence.mark_online(username)
    try:
        # Registered for the duration of the wait only - once _resolve_shard
        # returns (either a real shard or a give-up), status_relay has
        # nothing left to push to for this username: a relay has started
        # (or the client's about to be told to give up), and either way
        # there's no more "still searching" to report.
        status_relay.register(username, client_ws)
        try:
            shard_address = await _resolve_shard(username, active_game_index, rooms, room_shard_index, waiters)
        finally:
            status_relay.unregister(username)
        if shard_address is None:
            await client_ws.send(encode_json_message(MatchmakingTimeoutMessage()))
            return

        try:
            await _relay(client_ws, shard_address, shard_port, username)
        except (websockets.exceptions.ConnectionClosed, OSError) as error:
            _logger.warning("relay for '%s' (shard=%s) ended: %s", username, shard_address, error)
    finally:
        presence.mark_offline(username)


async def _main() -> None:
    redis_url = os.environ["REDIS_URL"]
    nats_url = os.environ["NATS_URL"]
    port = int(os.environ.get("WS_GATEWAY_PORT", WS_GATEWAY_PORT))
    # Every shard in a deployment listens on the same port (only
    # SHARD_ADDRESS - the hostname - differs between them, see
    # server/main.py's own KFCHESS_PORT); defaults to the same
    # protocol/types.py PORT a bare-metal shard already binds by default,
    # but configurable in case a deployment ever picks a different one.
    shard_port = int(os.environ.get("SHARD_PORT", SHARD_PORT))

    import nats

    active_game_index = ActiveGameIndex(redis_url)
    rooms = RedisRoomRegistry(redis_url)
    room_shard_index = RoomShardIndex(redis_url)
    presence = Presence(redis_url)
    waiters = _AllocationWaiters()
    status_relay = _StatusRelay()
    nats_connection = await nats.connect(nats_url)
    await _subscribe_matchmaking_events(nats_connection, waiters, status_relay)

    import redis as redis_lib

    # Explicit, short timeouts - redis-py's own default is *no* timeout at
    # all, which would hang this check (and, via
    # server/observability_server.py's own threaded WSGI server, only that
    # one request - but still worth failing fast) instead of failing it.
    _health_redis_client = redis_lib.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)

    health_port = int(os.environ.get("HEALTH_PORT", 9101))
    start_observability_server(
        health_port,
        {"redis": lambda: bool(_health_redis_client.ping()), "nats": lambda: nats_connection.is_connected},
    )

    async def _handler(client_ws) -> None:
        await _handle_client(
            active_game_index, rooms, room_shard_index, waiters, status_relay, presence, shard_port, client_ws
        )

    async with websockets.serve(_handler, "0.0.0.0", port):
        _logger.info(
            "ws-gateway listening on ws://0.0.0.0:%s (shard_port=%s redis=%s nats=%s)",
            port, shard_port, redis_url, nats_url,
        )
        await asyncio.Event().wait()


def main() -> None:  # pragma: no cover
    configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
