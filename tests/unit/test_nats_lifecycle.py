"""Real NATS, no mocks - server/nats/lifecycle.py's NatsLifecyclePublisher.
The publish-failure guard this file is really about (see that class's own
docstring on why it's guarded there, not just at each server/game_loop.py
call site) is exercised with a genuinely closed connection - that's what
makes publish() actually raise, not a stand-in for a failure a mocking
library would have to invent.

Skipped unless KFCHESS_TEST_NATS_URL is set:

    docker compose up -d nats
    KFCHESS_TEST_NATS_URL=nats://localhost:4222 python -m pytest tests/unit/test_nats_lifecycle.py
"""

import asyncio
import os

import pytest

NATS_URL = os.environ.get("KFCHESS_TEST_NATS_URL")
pytestmark = pytest.mark.skipif(NATS_URL is None, reason="set KFCHESS_TEST_NATS_URL to run these")


def test_game_created_publishes_a_real_event_a_real_subscriber_receives():
    import nats

    from server.nats.events import GameCreated
    from server.nats.lifecycle import NatsLifecyclePublisher

    async def scenario():
        publisher = await NatsLifecyclePublisher.connect(NATS_URL)
        subscriber_connection = await nats.connect(NATS_URL)
        received = []

        async def _on_message(msg) -> None:
            received.append(msg)

        sub = await subscriber_connection.subscribe(GameCreated.SUBJECT, cb=_on_message)

        try:
            await publisher.game_created("play-1", None, "alice", "bob")
            await asyncio.sleep(0.2)
        finally:
            await sub.unsubscribe()
            await subscriber_connection.close()
            await publisher.connection.close()
        return received

    received = asyncio.run(scenario())

    assert len(received) == 1
    event = GameCreated.decode(received[0].data)
    assert event.game_id == "play-1"
    assert event.white_username == "alice"
    assert event.black_username == "bob"


def test_game_finished_publishes_a_real_event_a_real_subscriber_receives():
    import nats

    from server.nats.events import GameFinished
    from server.nats.lifecycle import NatsLifecyclePublisher

    async def scenario():
        publisher = await NatsLifecyclePublisher.connect(NATS_URL)
        subscriber_connection = await nats.connect(NATS_URL)
        received = []

        async def _on_message(msg) -> None:
            received.append(msg)

        sub = await subscriber_connection.subscribe(GameFinished.SUBJECT, cb=_on_message)

        try:
            await publisher.game_finished("play-1", None, "alice", "bob", {"white": 1216, "black": 1184})
            await asyncio.sleep(0.2)
        finally:
            await sub.unsubscribe()
            await subscriber_connection.close()
            await publisher.connection.close()
        return received

    received = asyncio.run(scenario())

    assert len(received) == 1
    event = GameFinished.decode(received[0].data)
    assert event.ratings == {"white": 1216, "black": 1184}


# The guarantee NatsLifecyclePublisher.game_created's own internal
# try/except exists for - a caller must never have to handle an exception
# from this call itself (see server/game_loop.py's own belt-and-suspenders
# try/except around every call site, which this backs up rather than
# depends on). A closed connection is a real, not simulated, publish
# failure - nats-py raises when publish() is called on one.
def test_game_created_swallows_a_real_publish_failure_instead_of_raising():
    from server.nats.lifecycle import NatsLifecyclePublisher

    async def scenario():
        publisher = await NatsLifecyclePublisher.connect(NATS_URL)
        await publisher.connection.close()

        await publisher.game_created("play-1", None, "alice", "bob")  # must not raise

    asyncio.run(scenario())


def test_game_finished_swallows_a_real_publish_failure_instead_of_raising():
    from server.nats.lifecycle import NatsLifecyclePublisher

    async def scenario():
        publisher = await NatsLifecyclePublisher.connect(NATS_URL)
        await publisher.connection.close()

        # must not raise
        await publisher.game_finished("play-1", None, "alice", "bob", {"white": 1200, "black": 1200})

    asyncio.run(scenario())
