# Game-Allocator-only image: this service never touches the game engine,
# a websocket, or Postgres - just Redis (for the room-ownership lease and
# the shard registry) and NATS (subscribe match.found, publish
# game.allocated).
FROM python:3.11-slim

WORKDIR /app

COPY services/game_allocator/requirements.txt services/game_allocator/requirements.txt
RUN pip install --no-cache-dir -r services/game_allocator/requirements.txt

COPY services/__init__.py services/__init__.py
# Whole directory, same as services/matchmaker/Dockerfile's own server/redis/
# copy - this service only imports shard_registry.py from it, but nothing
# else in there depends on anything outside server/redis/ itself.
COPY server/redis/ server/redis/
COPY services/game_allocator/ services/game_allocator/

CMD ["python", "-m", "services.game_allocator.main"]
