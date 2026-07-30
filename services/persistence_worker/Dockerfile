# Persistence-Worker-only image: this service never touches the game
# engine, a websocket, or Redis - just Postgres (durable game history) and
# NATS (subscribe game.finished).
FROM python:3.11-slim

WORKDIR /app

COPY services/persistence_worker/requirements.txt services/persistence_worker/requirements.txt
RUN pip install --no-cache-dir -r services/persistence_worker/requirements.txt

COPY services/__init__.py services/__init__.py
COPY server/logging_config.py server/logging_config.py
COPY server/observability_server.py server/observability_server.py
# Server_Design.md §8's own batch-flush knobs (PERSISTENCE_BATCH_SIZE/
# PERSISTENCE_BATCH_FLUSH_INTERVAL_MS) - this service's own main.py imports
# them directly, same reasoning as the two files just above.
COPY server/server_config.py server/server_config.py
# Whole directory, same precedent as services/matchmaker/Dockerfile's own
# server/redis/ copy - this service only imports game_history.py from it,
# but nothing else in server/postgres/ depends on anything outside it.
COPY server/postgres/ server/postgres/
COPY services/persistence_worker/ services/persistence_worker/

CMD ["python", "-m", "services.persistence_worker.main"]
