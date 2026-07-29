# API-Gateway-only image: this service only ever imports
# server/postgres/accounts.py (+ its own server/accounts.py dependency for
# the shared Account/_hash_password), server/redis/matchmaking.py,
# server/redis/busy_set.py, and server/redis/rooms.py (+ its own
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
COPY server/accounts.py server/accounts.py
COPY server/rooms.py server/rooms.py
COPY server/redis/ server/redis/
COPY server/postgres/ server/postgres/
COPY services/api_gateway/ services/api_gateway/

EXPOSE 8080

CMD ["python", "-m", "services.api_gateway.main"]
