"""server/game_loop.py's shared tick loop treats a game that raises mid-tick as a
game that just ended abnormally (see GameLoop._fail_game), not a reason to take the
whole tick loop - and thus every other concurrently-running game - down with it.

Also covers GameLoop's own wiring of its optional active_game_index dependency
(see server/interfaces.py's ActiveGameIndexProtocol) - a real, if minimal,
in-memory fake (_FakeActiveGameIndex below), not a mock, the same "real object
standing in for the Redis-backed one" approach every other optional GameLoop
dependency already gets exercised with.

Exercised directly against GameLoop rather than through a full running server (see
tests/integration/test_server_ws.py), since a real GameSession/GameEngine has no dial
to make it misbehave on cue - _CrashingGameSession below is a real GameSession in
every other respect, its tick the one thing overridden.
"""

import asyncio
import contextlib
from typing import Dict, Optional

from boardio.board_parser import parse
from model.piece import BLACK, WHITE
from server.connections import ConnectionRegistry
from server.game_loop import ActiveGame, GameLoop
from server.interfaces import ActiveGameLocation, FairnessSnapshot
from server.publisher import NetworkPublisher
from server.rooms import RoomRegistry
from server.session import GameSession
from server.sqlite.accounts import UserStore
from server.sqlite.accounts_db import open_accounts_database
from server.sqlite.rating_store import RatingStore

STARTING_BOARD = "wR . .\n. . .\n. . ."


class _FakeActiveGameIndex:
    def __init__(self):
        self._locations: Dict[str, ActiveGameLocation] = {}

    def set(self, username: str, location: ActiveGameLocation) -> None:
        self._locations[username] = location

    def remove(self, username: str) -> None:
        self._locations.pop(username, None)

    def get(self, username: str) -> Optional[ActiveGameLocation]:
        return self._locations.get(username)


class _CrashingGameSession(GameSession):
    def tick(self, elapsed_ms):
        raise RuntimeError("boom")


# A real, minimal in-memory fake standing in for
# server/nats/lifecycle.py's NatsLifecyclePublisher - same "real object,
# not a mock" approach as _FakeActiveGameIndex above. Records every publish
# rather than actually reaching NATS, so a test can assert on exactly what
# _fail_game/_advance_game handed it.
class _FakeLifecyclePublisher:
    def __init__(self):
        self.created = []
        self.finished = []

    async def game_created(self, game_id, room_id, white_username, black_username):
        self.created.append((game_id, room_id, white_username, black_username))

    async def game_finished(self, game_id, room_id, white_username, black_username, ratings):
        self.finished.append((game_id, room_id, white_username, black_username, ratings))


# A real, minimal in-memory fake standing in for
# server/redis/fairness_checkpoint.py's FairnessCheckpoint - same "real
# object, not a mock" approach as every other optional GameLoop dependency's
# own fake in this file.
class _FakeFairnessCheckpoint:
    def __init__(self):
        self._snapshots: Dict[str, FairnessSnapshot] = {}

    def set(self, game_id: str, snapshot: FairnessSnapshot) -> None:
        self._snapshots[game_id] = snapshot

    def remove(self, game_id: str) -> None:
        self._snapshots.pop(game_id, None)

    def get(self, game_id: str) -> Optional[FairnessSnapshot]:
        return self._snapshots.get(game_id)


def _rating_store():
    database = open_accounts_database(":memory:")
    user_store = UserStore(database)
    for username in ("alice", "bob", "carol", "dave"):
        user_store.login(username, "secret123")
    return RatingStore(database)


def _make_loop(
    rating_store,
    rooms=None,
    active_game_index=None,
    shard_address=None,
    lifecycle_publisher=None,
    fairness_checkpoint=None,
):
    return GameLoop(
        lambda: parse(STARTING_BOARD),
        rating_store,
        rooms if rooms is not None else RoomRegistry(),
        ConnectionRegistry(),
        matchmaking_timeout_ms=60_000,
        disconnect_grace_ms=20_000,
        tick_interval_s=0.01,
        active_game_index=active_game_index,
        shard_address=shard_address,
        lifecycle_publisher=lifecycle_publisher,
        fairness_checkpoint=fairness_checkpoint,
    )


def test_a_crashing_games_tick_does_not_stop_a_healthy_games_tick():
    async def scenario():
        rating_store = _rating_store()
        loop = _make_loop(rating_store)

        healthy_session = GameSession(parse(STARTING_BOARD), rating_store, "alice", "bob")
        loop._games["healthy"] = ActiveGame(session=healthy_session, publisher=NetworkPublisher(healthy_session.bus))

        crashing_session = _CrashingGameSession(parse(STARTING_BOARD), rating_store, "carol", "dave")
        loop._games["crashing"] = ActiveGame(
            session=crashing_session, publisher=NetworkPublisher(crashing_session.bus)
        )

        task = asyncio.create_task(loop.run_forever())
        await asyncio.sleep(0.05)
        task.cancel()
        # If the crash weren't isolated, run_forever's own task would already have
        # died with the RuntimeError above - suppress only CancelledError here so
        # that (unlikely) failure mode still surfaces as this test erroring out.
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert "crashing" not in loop._games
        assert "healthy" in loop._games

    asyncio.run(scenario())


def test_a_crashing_games_room_is_closed_and_its_seats_are_freed():
    async def scenario():
        rating_store = _rating_store()
        rooms = RoomRegistry()
        room = rooms.create("carol")
        rooms.join(room.room_id, "dave")
        loop = _make_loop(rating_store, rooms)

        crashing_session = _CrashingGameSession(parse(STARTING_BOARD), rating_store, "carol", "dave")
        game = ActiveGame(
            session=crashing_session, publisher=NetworkPublisher(crashing_session.bus), room_id=room.room_id
        )
        loop._games[room.room_id] = game

        await loop._fail_game(room.room_id, game, RuntimeError("boom"))

        assert room.room_id not in loop._games
        assert rooms.room_for_username("carol") is None
        assert rooms.room_for_username("dave") is None

    asyncio.run(scenario())


def test_starting_a_game_records_both_seats_in_the_active_game_index():
    async def scenario():
        rating_store = _rating_store()
        active_game_index = _FakeActiveGameIndex()
        loop = _make_loop(rating_store, active_game_index=active_game_index, shard_address="test-shard")

        await loop._start_game("play-1", "alice", "bob")

        assert active_game_index.get("alice") == ActiveGameLocation(
            game_id="play-1", room_id=None, seat=WHITE, shard_address="test-shard"
        )
        assert active_game_index.get("bob") == ActiveGameLocation(
            game_id="play-1", room_id=None, seat=BLACK, shard_address="test-shard"
        )

    asyncio.run(scenario())


def test_starting_a_game_without_a_shard_address_does_not_write_the_active_game_index():
    async def scenario():
        rating_store = _rating_store()
        active_game_index = _FakeActiveGameIndex()
        # shard_address omitted - a misconfiguration (active_game_index set,
        # SHARD_ADDRESS not - see server/game_loop.py's own _start_game
        # guard) shouldn't write a location with no real shard to route to.
        loop = _make_loop(rating_store, active_game_index=active_game_index)

        await loop._start_game("play-1", "alice", "bob")

        assert active_game_index.get("alice") is None

    asyncio.run(scenario())


def test_starting_a_room_game_records_the_room_id_in_the_active_game_index():
    async def scenario():
        rating_store = _rating_store()
        active_game_index = _FakeActiveGameIndex()
        loop = _make_loop(rating_store, active_game_index=active_game_index, shard_address="test-shard")

        await loop._start_game("room-1", "alice", "bob", room_id="room-1")

        assert active_game_index.get("alice") == ActiveGameLocation(
            game_id="room-1", room_id="room-1", seat=WHITE, shard_address="test-shard"
        )

    asyncio.run(scenario())


def test_a_crashing_games_active_game_index_entries_are_removed():
    async def scenario():
        rating_store = _rating_store()
        rooms = RoomRegistry()
        room = rooms.create("carol")
        rooms.join(room.room_id, "dave")
        active_game_index = _FakeActiveGameIndex()
        loop = _make_loop(rating_store, rooms, active_game_index=active_game_index)

        crashing_session = _CrashingGameSession(parse(STARTING_BOARD), rating_store, "carol", "dave")
        game = ActiveGame(
            session=crashing_session, publisher=NetworkPublisher(crashing_session.bus), room_id=room.room_id
        )
        loop._games[room.room_id] = game
        active_game_index.set(
            "carol", ActiveGameLocation(game_id=room.room_id, room_id=room.room_id, seat=WHITE, shard_address="test-shard")
        )
        active_game_index.set(
            "dave", ActiveGameLocation(game_id=room.room_id, room_id=room.room_id, seat=BLACK, shard_address="test-shard")
        )

        await loop._fail_game(room.room_id, game, RuntimeError("boom"))

        assert active_game_index.get("carol") is None
        assert active_game_index.get("dave") is None

    asyncio.run(scenario())


def test_a_crashing_games_lifecycle_publisher_still_gets_game_finished():
    async def scenario():
        rating_store = _rating_store()
        rooms = RoomRegistry()
        room = rooms.create("carol")
        rooms.join(room.room_id, "dave")
        lifecycle_publisher = _FakeLifecyclePublisher()
        loop = _make_loop(rating_store, rooms, lifecycle_publisher=lifecycle_publisher)

        crashing_session = _CrashingGameSession(parse(STARTING_BOARD), rating_store, "carol", "dave")
        game = ActiveGame(
            session=crashing_session, publisher=NetworkPublisher(crashing_session.bus), room_id=room.room_id
        )
        loop._games[room.room_id] = game

        carol_rating = rating_store.rating_for("carol")
        dave_rating = rating_store.rating_for("dave")

        await loop._fail_game(room.room_id, game, RuntimeError("boom"))

        # Unchanged ratings - a crash never decides a winner, so
        # persistence-worker's own record_game still gets a real row for
        # this game (see services/persistence_worker/main.py), just with
        # no rating movement, rather than this game's history going
        # unwritten entirely.
        assert lifecycle_publisher.finished == [
            (room.room_id, room.room_id, "carol", "dave", {WHITE: carol_rating, BLACK: dave_rating})
        ]

    asyncio.run(scenario())


def test_a_crashing_games_lifecycle_publish_failure_does_not_prevent_cleanup():
    async def scenario():
        rating_store = _rating_store()
        rooms = RoomRegistry()
        room = rooms.create("carol")
        rooms.join(room.room_id, "dave")

        class _ExplodingLifecyclePublisher:
            async def game_created(self, *args, **kwargs):
                pass

            async def game_finished(self, *args, **kwargs):
                raise RuntimeError("nats is down")

        loop = _make_loop(rating_store, rooms, lifecycle_publisher=_ExplodingLifecyclePublisher())

        crashing_session = _CrashingGameSession(parse(STARTING_BOARD), rating_store, "carol", "dave")
        game = ActiveGame(
            session=crashing_session, publisher=NetworkPublisher(crashing_session.bus), room_id=room.room_id
        )
        loop._games[room.room_id] = game

        await loop._fail_game(room.room_id, game, RuntimeError("boom"))

        assert room.room_id not in loop._games
        assert rooms.room_for_username("carol") is None

    asyncio.run(scenario())


# ---- Server_Design.md §9's own lightweight fairness checkpoint ----


# Forces the game-over branch on cue, the same "override one method" idea
# as _CrashingGameSession above - not a real king-capture, since this is
# about _advance_game's own cleanup wiring, not game-over detection itself.
class _GameOverGameSession(GameSession):
    def finalize_ratings_if_game_over(self):
        return {WHITE: 1210, BLACK: 1190}


def test_no_fairness_checkpoint_is_written_before_the_interval_elapses():
    async def scenario():
        rating_store = _rating_store()
        fairness_checkpoint = _FakeFairnessCheckpoint()
        loop = _make_loop(rating_store, fairness_checkpoint=fairness_checkpoint)

        session = GameSession(parse(STARTING_BOARD), rating_store, "alice", "bob")
        game = ActiveGame(session=session, publisher=NetworkPublisher(session.bus))
        loop._games["play-1"] = game

        await loop._advance_game("play-1", game, whole_ms=3000)  # under FAIRNESS_CHECKPOINT_INTERVAL_MS (5000)

        assert fairness_checkpoint.get("play-1") is None

    asyncio.run(scenario())


def test_a_fairness_checkpoint_is_written_once_the_interval_elapses():
    async def scenario():
        rating_store = _rating_store()
        fairness_checkpoint = _FakeFairnessCheckpoint()
        loop = _make_loop(rating_store, fairness_checkpoint=fairness_checkpoint)

        session = GameSession(parse(STARTING_BOARD), rating_store, "alice", "bob")
        game = ActiveGame(session=session, publisher=NetworkPublisher(session.bus))
        loop._games["play-1"] = game

        await loop._advance_game("play-1", game, whole_ms=3000)
        await loop._advance_game("play-1", game, whole_ms=3000)  # total 6000ms, crosses the 5000ms interval

        snapshot = fairness_checkpoint.get("play-1")
        assert snapshot is not None
        assert snapshot.elapsed_ms == 6000
        assert snapshot.white_score == 0
        assert snapshot.black_score == 0
        # STARTING_BOARD ("wR . .\n. . .\n. . .") has exactly one piece, a
        # white rook - no black pieces at all.
        assert snapshot.white_pieces_remaining == 1
        assert snapshot.black_pieces_remaining == 0

    asyncio.run(scenario())


def test_a_fairness_checkpoint_is_removed_on_normal_game_over():
    async def scenario():
        rating_store = _rating_store()
        fairness_checkpoint = _FakeFairnessCheckpoint()
        fairness_checkpoint.set(
            "play-1", FairnessSnapshot(white_score=0, black_score=0, elapsed_ms=1000, white_pieces_remaining=1, black_pieces_remaining=1)
        )
        loop = _make_loop(rating_store, fairness_checkpoint=fairness_checkpoint)

        session = _GameOverGameSession(parse(STARTING_BOARD), rating_store, "alice", "bob")
        game = ActiveGame(session=session, publisher=NetworkPublisher(session.bus))
        loop._games["play-1"] = game

        await loop._advance_game("play-1", game, whole_ms=100)

        assert fairness_checkpoint.get("play-1") is None

    asyncio.run(scenario())


def test_a_fairness_checkpoint_is_removed_on_crash():
    async def scenario():
        rating_store = _rating_store()
        fairness_checkpoint = _FakeFairnessCheckpoint()
        fairness_checkpoint.set(
            "play-1", FairnessSnapshot(white_score=0, black_score=0, elapsed_ms=1000, white_pieces_remaining=1, black_pieces_remaining=1)
        )
        loop = _make_loop(rating_store, fairness_checkpoint=fairness_checkpoint)

        crashing_session = _CrashingGameSession(parse(STARTING_BOARD), rating_store, "alice", "bob")
        game = ActiveGame(session=crashing_session, publisher=NetworkPublisher(crashing_session.bus))
        loop._games["play-1"] = game

        await loop._fail_game("play-1", game, RuntimeError("boom"))

        assert fairness_checkpoint.get("play-1") is None

    asyncio.run(scenario())
