# Matchmaker-only image: this service only ever imports
# server/redis/matchmaking.py plus its own two small dependencies
# (server/interfaces.py, server/server_config.py) - none of the game
# engine (model/, rules/, physics/, realtime/, engine/, boardio/, events/,
# protocol/) or the SQLite/Postgres stores, so none of that is copied here.
FROM python:3.11-slim

WORKDIR /app

COPY services/matchmaker/requirements.txt services/matchmaker/requirements.txt
RUN pip install --no-cache-dir -r services/matchmaker/requirements.txt

COPY services/__init__.py services/__init__.py
COPY server/interfaces.py server/interfaces.py
COPY server/server_config.py server/server_config.py
COPY server/logging_config.py server/logging_config.py
COPY server/observability_server.py server/observability_server.py
COPY server/redis/ server/redis/
# server/nats/events.py's typed MatchmakingRequested/MatchmakingStatus/
# MatchmakingTimeout/MatchFound - this service's own main.py builds/decodes
# NATS payloads through these instead of a raw dict now (see that module's
# own docstring).
COPY server/nats/ server/nats/
COPY services/matchmaker/ services/matchmaker/

CMD ["python", "-m", "services.matchmaker.main"]
