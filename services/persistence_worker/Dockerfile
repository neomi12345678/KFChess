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
# Whole directory, same precedent as services/matchmaker/Dockerfile's own
# server/redis/ copy - this service only imports game_history.py from it,
# but nothing else in server/postgres/ depends on anything outside it.
COPY server/postgres/ server/postgres/
COPY services/persistence_worker/ services/persistence_worker/

CMD ["python", "-m", "services.persistence_worker.main"]
