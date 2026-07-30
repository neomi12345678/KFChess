"""Standalone Game Allocator service - subscribes to the Matchmaker's
match.found event *and* the API Gateway's room.opponent_joined event (see
services/api_gateway/main.py's handle_join_room), and decides which Game
Server Shard should host the new game either way - the "Game Allocator"
role from Server_Design.md §3-4 (docs/server-scaling-design branch). Which
shard "wins" an allocation is discovered from the real Shard Registry
(server/redis/shard_registry.py) - each game-server heartbeats its own
address into Redis, and this service just picks a live one (server/main.py's
own registration side resolves Server_Design.md §12's open question on
this). The room-ownership lease itself (Server_Design.md §4 - "a lease, not
just a registry entry") is real too, acquired in Redis before the game is
ever announced, not faked: a freshly-minted game_id (or, for a room, the
room_id itself) whose lease is already held would mean this same match/room
was somehow allocated twice (shouldn't happen with one Matchmaker instance
publishing match.found exactly once per pair, or one RedisRoomRegistry.join
ever letting exactly one joiner become the opponent, but the lease is what
would actually catch it if it ever did, rather than silently starting the
same game_id in two places).

Publishes:
    game.allocated  {"game_id": str, "room_id": str|null, "white_username":
                      str, "black_username": str, "shard_address": str}

For a PLAY match, room_id is null and game_id is freshly minted
("play-<hex>"). For a room, game_id *is* the room_id (the room's own
identity already uniquely names its game - see _handle_room_opponent_joined
below), and creator/opponent map onto white_username/black_username exactly
the way GameLoop.start_room_game's existing in-process path already does.

Every Game Server Shard subscribes to this (see server/game_loop.py's
start_game_allocation_relay) and filters on shard_address itself - only the
addressed shard actually starts the game; every other shard ignores the
event. game.allocated is also this service's own real-time signal for
services/ws_gateway/main.py's _AllocationWaiters (a client waiting on a
still-pending PLAY/room-opponent allocation), and shard_address is what
lets it open its own internal relay connection once resolved. Deliberately
kept as "game.allocated", not renamed to the document's literal
"game-created" - server/nats/lifecycle.py already publishes a real,
different game.created event, fired by the shard itself once it starts
hosting a room, carrying no shard address; colliding the two names would be
a worse mismatch than keeping today's distinct name and just enriching its
payload.

Also maintains the Server_Design.md §4 `room_id -> worker` mapping itself
(server/redis/room_shard_index.py's RoomShardIndex, see its own docstring)
- written the instant a room's lease is acquired, for a room-based
allocation only (never a PLAY match, which has no room_id for anyone to
look up). This is what lets a spectator joining a room later (see
services/api_gateway/main.py's handle_join_room and
services/ws_gateway/main.py's _resolve_shard) learn which shard to relay
to without ever needing its own allocation event - the room's game already
exists by the time a spectator joins, so there is nothing to wait for.
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Optional

import nats
import redis

from server.redis.room_shard_index import RoomShardIndex
from server.redis.shard_registry import ShardRegistry

_logger = logging.getLogger(__name__)


def _acquire_lease(redis_client, game_id: str, shard_address: str, ttl_ms: int = 5000) -> bool:
    # NX: only set if not already held. PX: auto-expires, so a crashed
    # allocator (or a shard that never actually starts the game) never
    # permanently strands a game_id's lease.
    return bool(redis_client.set(f"kfchess:game:{game_id}:owner", shard_address, nx=True, px=ttl_ms))


# Shared by _handle_match_found and _handle_room_opponent_joined below - the
# only two things that ever differ between a PLAY match and a room are how
# game_id/room_id are computed and where white/black come from, both
# resolved by the caller before this runs.
async def _allocate(
    redis_client,
    nats_connection,
    room_shard_index: RoomShardIndex,
    shard_address: str,
    game_id: str,
    room_id: Optional[str],
    white_username: str,
    black_username: str,
) -> None:
    if not _acquire_lease(redis_client, game_id, shard_address):
        _logger.error("failed to acquire lease for game_id %s - not allocating", game_id)
        return

    # The Server_Design.md §4 room_id -> worker mapping itself - room_id is
    # None for a PLAY match (nothing for a spectator to ever look up), set
    # for a room (game_id *is* the room_id here - see this module's own
    # docstring). Written here, the instant the lease is acquired, rather
    # than by the shard once it actually starts the game: a spectator
    # joining a room only ever needs to know *which shard*, never anything
    # the shard itself would have to compute.
    if room_id is not None:
        room_shard_index.set(room_id, shard_address)

    out_payload = {
        "game_id": game_id,
        "room_id": room_id,
        "white_username": white_username,
        "black_username": black_username,
        "shard_address": shard_address,
    }
    await nats_connection.publish("game.allocated", json.dumps(out_payload).encode("utf-8"))
    _logger.info("allocated game %s ('%s' vs '%s') to %s", game_id, white_username, black_username, shard_address)


async def _handle_match_found(
    redis_client, nats_connection, room_shard_index: RoomShardIndex, shard_address: Optional[str], msg
) -> None:
    if shard_address is None:
        _logger.error("no live Game Server Shard registered - dropping match.found (%s)", msg.data)
        return

    payload = json.loads(msg.data)
    # Freshly minted per allocation - the in-process "play-N" incrementing
    # counter GameLoop._try_start_a_match used doesn't survive as a
    # cross-process id scheme (nothing here coordinates a shared counter).
    game_id = f"play-{uuid.uuid4().hex[:8]}"
    await _allocate(
        redis_client,
        nats_connection,
        room_shard_index,
        shard_address,
        game_id,
        None,
        payload["white_username"],
        payload["black_username"],
    )


# Mirrors _handle_match_found for the room-flow's own equivalent event,
# published the instant a room's opponent seat fills (see
# services/api_gateway/main.py's handle_join_room) - the one structural
# difference: a room's game_id *is* its own room_id, never a freshly minted
# one, since the room already has a unique, wire-visible identity of its
# own. creator/opponent map onto white/black exactly the way
# GameLoop.start_room_game's existing in-process path already does.
async def _handle_room_opponent_joined(
    redis_client, nats_connection, room_shard_index: RoomShardIndex, shard_address: Optional[str], msg
) -> None:
    if shard_address is None:
        _logger.error("no live Game Server Shard registered - dropping room.opponent_joined (%s)", msg.data)
        return

    payload = json.loads(msg.data)
    room_id = payload["room_id"]
    await _allocate(
        redis_client,
        nats_connection,
        room_shard_index,
        shard_address,
        room_id,
        room_id,
        payload["creator"],
        payload["opponent"],
    )


async def _main() -> None:
    redis_url = os.environ["REDIS_URL"]
    nats_url = os.environ["NATS_URL"]

    redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
    registry = ShardRegistry(redis_url)
    room_shard_index = RoomShardIndex(redis_url)
    nats_connection = await nats.connect(nats_url)

    async def _on_match_found(msg) -> None:
        shard_address = registry.pick_shard()
        await _handle_match_found(redis_client, nats_connection, room_shard_index, shard_address, msg)

    async def _on_room_opponent_joined(msg) -> None:
        shard_address = registry.pick_shard()
        await _handle_room_opponent_joined(redis_client, nats_connection, room_shard_index, shard_address, msg)

    await nats_connection.subscribe("match.found", cb=_on_match_found)
    await nats_connection.subscribe("room.opponent_joined", cb=_on_room_opponent_joined)

    _logger.info("game-allocator running (redis=%s nats=%s)", redis_url, nats_url)
    await asyncio.Event().wait()  # driven entirely by the subscription callbacks above


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
