"""services/api_gateway/main.py's _reconcile_started_rooms_once - the
single-sweep logic behind _reconcile_started_rooms's own infinite loop,
split out specifically so it's callable here without going through that
loop's own asyncio.sleep(ROOM_RECONCILE_INTERVAL_S).

Small hand-written fakes below, not a mocking library - just enough of
RedisRoomRegistry's/RoomShardIndex's own interface (started_room_ids/close,
get) for this function to drive.
"""

import asyncio

from services.api_gateway.main import _reconcile_started_rooms_once


class _FakeRooms:
    def __init__(self, started_room_ids, fail_room_ids=frozenset()):
        self._started_room_ids = list(started_room_ids)
        self._fail_room_ids = set(fail_room_ids)
        self.closed = []

    def started_room_ids(self):
        return list(self._started_room_ids)

    def close(self, room_id):
        if room_id in self._fail_room_ids:
            raise RuntimeError(f"simulated failure closing {room_id}")
        self.closed.append(room_id)


class _FakeRoomShardIndex:
    def __init__(self, owned_room_ids=frozenset()):
        self._owned = set(owned_room_ids)

    def get(self, room_id):
        return "shard-1" if room_id in self._owned else None


# The bug this covers: room-a raising on close() used to abort the whole
# `for room_id in rooms.started_room_ids()` loop early, so room-b (also
# suspected this same pass, and perfectly closeable) was silently skipped
# too, and the still_missing this function returns (next pass's own
# `suspected`) never reflected either room.
def test_a_room_that_fails_to_close_does_not_block_other_suspected_rooms_this_pass():
    rooms = _FakeRooms(started_room_ids=["room-a", "room-b"], fail_room_ids={"room-a"})
    room_shard_index = _FakeRoomShardIndex(owned_room_ids=set())
    suspected = {"room-a", "room-b"}

    still_missing = asyncio.run(_reconcile_started_rooms_once(rooms, room_shard_index, suspected))

    assert rooms.closed == ["room-b"]
    # Both still reported missing a shard - room-a's own failed close is
    # retried next pass, not silently forgotten.
    assert still_missing == {"room-a", "room-b"}


def test_a_room_with_a_live_shard_owner_is_never_suspected_or_closed():
    rooms = _FakeRooms(started_room_ids=["room-a"])
    room_shard_index = _FakeRoomShardIndex(owned_room_ids={"room-a"})

    still_missing = asyncio.run(_reconcile_started_rooms_once(rooms, room_shard_index, suspected=set()))

    assert still_missing == set()
    assert rooms.closed == []


# Requires two consecutive misses (see _reconcile_started_rooms's own
# docstring) - a room missing its shard for the very first time this pass
# is only ever suspected, not closed yet.
def test_a_room_missing_a_shard_for_the_first_time_is_only_suspected_not_closed():
    rooms = _FakeRooms(started_room_ids=["room-a"])
    room_shard_index = _FakeRoomShardIndex(owned_room_ids=set())

    still_missing = asyncio.run(_reconcile_started_rooms_once(rooms, room_shard_index, suspected=set()))

    assert still_missing == {"room-a"}
    assert rooms.closed == []
