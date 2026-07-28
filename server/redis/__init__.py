"""Redis-backed sibling of server/matchmaking.py's in-memory
MatchmakingQueue - used only when the Dockerized deployment sets
REDIS_URL (see server/main.py's _build_matchmaking and
docker-compose.yml). The in-memory original is untouched and stays the
default for a bare-metal run.

    matchmaking.py   RedisMatchmakingQueue
"""
