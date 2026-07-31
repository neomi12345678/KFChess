"""services/ws_gateway/main.py's _AllocationWaiters - the {username: Future}
table _resolve_shard uses to learn which shard a still-pending PLAY/room
allocation landed on. No real Redis/NATS/websocket needed for any of this -
it's a plain in-process dict plus asyncio.Future bookkeeping.

Covers cancel() specifically: _resolve_shard calls it whenever its own wait
ends without a match.found/matchmaking.timeout event ever arriving for this
username (the client disconnected mid-wait, or the outer safety-net timeout
fired) - without it, the Future wait_for() registered stays in _pending
forever, since resolve() is the only other thing that ever pops it out.
"""

import asyncio

from services.ws_gateway.main import _AllocationWaiters


def test_cancel_pops_a_still_pending_future_out_of_the_table():
    async def scenario():
        waiters = _AllocationWaiters()
        future = waiters.wait_for("alice")
        assert "alice" in waiters._pending

        waiters.cancel("alice")

        assert "alice" not in waiters._pending
        assert future.cancelled()

    asyncio.run(scenario())


def test_cancel_is_a_no_op_for_a_username_never_registered():
    waiters = _AllocationWaiters()

    waiters.cancel("nobody")  # must not raise

    assert "nobody" not in waiters._pending


def test_cancel_does_not_touch_an_already_resolved_future():
    async def scenario():
        waiters = _AllocationWaiters()
        future = waiters.wait_for("alice")
        waiters.resolve("alice", "shard-a")  # pops it, sets a real result

        waiters.cancel("alice")  # already gone - must not raise or re-touch it

        assert await future == "shard-a"

    asyncio.run(scenario())


def test_resolve_after_cancel_is_a_safe_no_op():
    async def scenario():
        waiters = _AllocationWaiters()
        waiters.wait_for("alice")
        waiters.cancel("alice")

        waiters.resolve("alice", "shard-a")  # must not raise - nothing left to resolve

        assert "alice" not in waiters._pending

    asyncio.run(scenario())
