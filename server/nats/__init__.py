"""NATS-backed publisher for GameLoop's two coarse game-lifecycle events
(game-created, game-finished) - used only when the Dockerized deployment
sets NATS_URL (see server/main.py and docker-compose.yml). Entirely
optional: GameLoop treats no publisher (None) as a no-op.

    lifecycle.py   NatsLifecyclePublisher
"""
