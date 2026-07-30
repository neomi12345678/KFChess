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
COPY server/redis/ server/redis/
COPY services/matchmaker/ services/matchmaker/

CMD ["python", "-m", "services.matchmaker.main"]
