# WS-Gateway-only image: this service never touches Postgres or SQLite -
# just Redis (server/redis/active_game_index.py to resolve a seated
# player's/reconnect's shard, server/redis/rooms.py's RedisRoomRegistry +
# server/redis/room_shard_index.py's RoomShardIndex to resolve a
# spectator's shard - see services/ws_gateway/main.py's own _resolve_shard)
# and NATS (subscribe game.allocated/matchmaking.timeout/matchmaking.status
# while a client is still waiting for one). protocol/ is needed in full -
# this service builds/decodes real wire messages (IdentifyMessage/
# IdentifyAckMessage/MatchmakingTimeoutMessage/MatchmakingStatusMessage/
# ErrorMessage) the same way a real client or Shard would - and pulls in
# more of the game engine transitively than it looks like at first glance:
# protocol/game_messages.py (ErrorMessage) imports protocol/snapshot_codec.py
# (for position_to_json), which imports model/ *and* events/observers.py,
# which in turn imports boardio/algebraic_notation.py. None of that code
# ever actually *runs* here (this service never builds a snapshot or an
# observer), it just has to be importable - so model/, events/, and
# boardio/ all come along, none of the rest of the game engine (rules/,
# physics/, realtime/, engine/) does. server/rooms.py is likewise never
# *run* here (RoomRegistry itself isn't used, only the Room/RoomError
# shapes) - server/redis/rooms.py's own RedisRoomRegistry imports them, the
# same reason services/api_gateway/main.py's own Dockerfile already copies
# this one file on its own rather than the whole server/ package.
FROM python:3.11-slim

WORKDIR /app

COPY services/ws_gateway/requirements.txt services/ws_gateway/requirements.txt
RUN pip install --no-cache-dir -r services/ws_gateway/requirements.txt

COPY services/__init__.py services/__init__.py
COPY protocol/ protocol/
COPY model/ model/
COPY events/ events/
COPY boardio/ boardio/
COPY server/interfaces.py server/interfaces.py
COPY server/server_config.py server/server_config.py
COPY server/rooms.py server/rooms.py
COPY server/redis/ server/redis/
COPY services/ws_gateway/ services/ws_gateway/

CMD ["python", "-m", "services.ws_gateway.main"]
