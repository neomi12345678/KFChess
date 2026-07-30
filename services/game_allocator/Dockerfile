# Game-Allocator-only image: this service never touches the game engine,
# a websocket, or Postgres - just Redis (room-ownership lease, shard
# registry, room<->shard/active-game/busy-set/fairness-checkpoint indices -
# see services/game_allocator/main.py's own recovery sweep) and NATS
# (subscribe match.found/room.opponent_joined, publish game.allocated).
# server/rooms.py (Room/RoomError) is needed too now - server/redis/rooms.py's
# RedisRoomRegistry imports the shared shapes from there, same reason
# services/api_gateway/main.py's own Dockerfile already copies this one file
# on its own rather than the whole server/ package.
FROM python:3.11-slim

WORKDIR /app

COPY services/game_allocator/requirements.txt services/game_allocator/requirements.txt
RUN pip install --no-cache-dir -r services/game_allocator/requirements.txt

COPY services/__init__.py services/__init__.py
COPY protocol/ protocol/
COPY server/interfaces.py server/interfaces.py
COPY server/server_config.py server/server_config.py
COPY server/rooms.py server/rooms.py
# Whole directory, same as services/matchmaker/Dockerfile's own server/redis/
# copy.
COPY server/redis/ server/redis/
COPY services/game_allocator/ services/game_allocator/

CMD ["python", "-m", "services.game_allocator.main"]
