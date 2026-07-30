"""NATS-backed publisher for GameLoop's two coarse game-lifecycle events
(game-created, game-finished) - used only when the Dockerized deployment
sets NATS_URL (see server/main.py and docker-compose.yml). Entirely
optional: GameLoop treats no publisher (None) as a no-op.

    lifecycle.py   NatsLifecyclePublisher
    events.py      Typed payload contract (dataclass) per NATS subject,
                    shared by every standalone service in services/ that
                    publishes/subscribes to one - see its own docstring.
"""
