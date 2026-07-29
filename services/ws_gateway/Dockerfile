# WS-Gateway-only image: this service never touches Postgres, the game
# engine, or SQLite - just Redis (server/redis/active_game_index.py, to
# resolve which shard a username's game is on) and NATS (subscribe
# game.allocated/matchmaking.timeout while a client is still waiting for
# one). protocol/ is needed in full - this service builds/decodes real
# wire messages (IdentifyMessage/IdentifyAckMessage/MatchmakingTimeoutMessage/
# ErrorMessage) the same way a real client or Shard would, even though it
# never acts on anything else it relays.
FROM python:3.11-slim

WORKDIR /app

COPY services/ws_gateway/requirements.txt services/ws_gateway/requirements.txt
RUN pip install --no-cache-dir -r services/ws_gateway/requirements.txt

COPY services/__init__.py services/__init__.py
COPY protocol/ protocol/
COPY server/interfaces.py server/interfaces.py
COPY server/server_config.py server/server_config.py
COPY server/redis/ server/redis/
COPY services/ws_gateway/ services/ws_gateway/

CMD ["python", "-m", "services.ws_gateway.main"]
