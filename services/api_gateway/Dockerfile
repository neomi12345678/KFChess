# API-Gateway-only image: this service only ever imports
# server/postgres/accounts.py (+ its own server/accounts.py dependency for
# the shared Account/InvalidCredentialsError/_hash_password),
# server/redis/matchmaking.py, server/redis/busy_set.py,
# server/redis/active_game_index.py, and server/redis/rooms.py (+ its own
# server/rooms.py dependency for the shared Room/RoomError) - none of the
# game engine (model/, rules/, physics/, realtime/, engine/, boardio/,
# events/, protocol/'s message classes aside) or SQLite stores, so none of
# that is copied here.
FROM python:3.11-slim

WORKDIR /app

COPY services/api_gateway/requirements.txt services/api_gateway/requirements.txt
RUN pip install --no-cache-dir -r services/api_gateway/requirements.txt

COPY services/__init__.py services/__init__.py
COPY protocol/ protocol/
COPY server/interfaces.py server/interfaces.py
COPY server/server_config.py server/server_config.py
COPY server/logging_config.py server/logging_config.py
COPY server/accounts.py server/accounts.py
COPY server/rooms.py server/rooms.py
COPY server/redis/ server/redis/
COPY server/postgres/ server/postgres/
# server/nats/events.py's typed MatchmakingRequested/RoomOpponentJoined/
# GameFinished - this service's own main.py builds/decodes NATS payloads
# through these instead of a raw dict now (see that module's own
# docstring).
COPY server/nats/ server/nats/
# get_server_ssl_context - only the stdlib ssl module at this import path,
# see tls_config.py's own docstring on why cryptography isn't needed here.
COPY tls_config.py .
COPY services/api_gateway/ services/api_gateway/

EXPOSE 8080

CMD ["python", "-m", "services.api_gateway.main"]
