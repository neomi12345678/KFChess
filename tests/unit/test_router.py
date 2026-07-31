"""CommandRouter's own docstring says its routing decisions are meant to be
exercised with plain Python values, never a real websocket/JSON - this pins
down exactly the branches that docstring calls out as the reason the split
exists: decide_login's four outcomes (fresh login, reconnect into a still-
disconnected active session, a persisted room resumed with the other side
already back online, and one resumed with the other side still offline),
the shared busy/free check every decide_play/decide_create_room/
decide_join_room starts with, and decide_game_command's seat authorization.
Built against real collaborators (GameLoop/RoomRegistry/RatingStore/
ConnectionRegistry are all cheap to construct directly), not fakes.
"""

from boardio.board_parser import parse
from model.piece import BLACK, WHITE
from model.position import Position
from protocol.game_messages import MoveMessage, build_jump, build_move
from server.connections import ConnectionRegistry
from server.game_loop import ActiveGame, GameLoop
from server.publisher import NetworkPublisher
from server.rooms import Room, RoomRegistry
from server.router import CommandRouter
from server.session import GameSession
from server.sqlite.accounts import UserStore
from server.sqlite.accounts_db import open_accounts_database
from server.sqlite.rating_store import RatingStore

STARTING_BOARD = "wR . .\n. . .\n. . ."


def _rating_store(*usernames):
    database = open_accounts_database(":memory:")
    user_store = UserStore(database)
    for username in usernames or ("alice", "bob"):
        user_store.login(username, "secret123")
    return RatingStore(database)


def _router(rating_store=None, rooms=None, connections=None, remote_rooms=None):
    rating_store = rating_store if rating_store is not None else _rating_store()
    rooms = rooms if rooms is not None else RoomRegistry()
    connections = connections if connections is not None else ConnectionRegistry()
    loop = GameLoop(
        lambda: parse(STARTING_BOARD),
        rating_store,
        rooms,
        connections,
        matchmaking_timeout_ms=60_000,
        disconnect_grace_ms=20_000,
    )
    return CommandRouter(rooms, loop, rating_store, connections, remote_rooms=remote_rooms), loop, rooms, connections


# A real, minimal in-memory fake standing in for server/redis/rooms.py's
# RedisRoomRegistry - same "real object, not a mock" approach as every
# other optional CommandRouter/GameLoop dependency's own test fake in this
# project (see tests/unit/test_server_game_loop.py's _FakeActiveGameIndex).
# Only implements room_for_username - the one method decide_identify's own
# RoomLookupProtocol (server/rooms.py) actually calls.
class _FakeRemoteRooms:
    def __init__(self, rooms_by_username=None):
        self._rooms_by_username = rooms_by_username or {}

    def room_for_username(self, username):
        return self._rooms_by_username.get(username)


def _seat_alice_and_bob(loop, rating_store, game_id="play-1"):
    session = GameSession(parse(STARTING_BOARD), rating_store, "alice", "bob")
    loop._games[game_id] = ActiveGame(session=session, publisher=NetworkPublisher(session.bus))
    return session


# ---- decide_login ----


def test_decide_login_a_fresh_username_is_accepted_with_no_reconnect_fields():
    rating_store = _rating_store()
    router, _loop, _rooms, _connections = _router(rating_store=rating_store)

    decision = router.decide_login("alice", 1200)

    assert decision.ack.accepted is True
    assert decision.ack.reconnected is None
    assert decision.ack.resuming_room_id is None
    assert decision.start_room is None


def test_decide_login_reconnects_a_still_disconnected_seat_of_an_active_session():
    rating_store = _rating_store()
    router, loop, _rooms, _connections = _router(rating_store=rating_store)
    session = _seat_alice_and_bob(loop, rating_store)
    session.mark_disconnected(WHITE)

    decision = router.decide_login("alice", 1200)

    assert decision.ack.accepted is True
    assert decision.ack.reconnected is True
    assert decision.ack.color == WHITE
    assert decision.start_room is None
    assert session.is_disconnected(WHITE) is False  # mark_reconnected was called


def test_decide_login_resumes_a_persisted_room_when_the_other_side_is_already_online():
    rating_store = _rating_store()
    rooms = RoomRegistry()
    connections = ConnectionRegistry()
    room = rooms.create("alice")
    rooms.join(room.room_id, "bob")  # both seats filled, but no GameSession has started for it yet
    connections.set("bob", object())
    router, _loop, _rooms, _connections = _router(rating_store=rating_store, rooms=rooms, connections=connections)

    decision = router.decide_login("alice", 1200)

    assert decision.ack.accepted is True
    assert decision.ack.reconnected is True
    assert decision.ack.color == WHITE  # alice is the room's creator
    assert decision.start_room is room


def test_decide_login_reports_resuming_room_id_when_the_other_side_is_still_offline():
    rating_store = _rating_store()
    rooms = RoomRegistry()
    room = rooms.create("alice")
    rooms.join(room.room_id, "bob")
    router, _loop, _rooms, _connections = _router(rating_store=rating_store, rooms=rooms)

    decision = router.decide_login("alice", 1200)

    assert decision.ack.accepted is True
    assert decision.ack.resuming_room_id == room.room_id
    assert decision.ack.reconnected is None
    assert decision.start_room is None


# ---- shared busy/free check ----


def test_decide_play_is_rejected_while_already_in_a_pending_room():
    rooms = RoomRegistry()
    rooms.create("alice")
    router, _loop, _rooms, _connections = _router(rooms=rooms)

    ack = router.decide_play("alice")

    assert ack.accepted is False
    assert ack.reason == "already_in_game"


def test_decide_play_enqueues_a_free_username_into_matchmaking():
    router, loop, _rooms, _connections = _router()

    ack = router.decide_play("alice")

    assert ack.accepted is True
    assert ack.reason == "queued"
    assert loop.matchmaking.is_waiting("alice") is True


def test_decide_create_room_is_rejected_while_already_queued():
    router, loop, _rooms, _connections = _router()
    loop.matchmaking.enqueue("alice", rating=1200)

    ack = router.decide_create_room("alice")

    assert ack.accepted is False
    assert ack.reason == "already_queued"


def test_decide_create_room_succeeds_for_a_free_username():
    router, _loop, _rooms, _connections = _router()

    ack = router.decide_create_room("alice")

    assert ack.accepted is True
    assert ack.room_id is not None


# ---- decide_join_room ----


def test_decide_join_room_reports_room_not_found():
    router, _loop, _rooms, _connections = _router()

    decision = router.decide_join_room("alice", "nonexistent")

    assert decision.ack.accepted is False
    assert decision.ack.reason == "room_not_found"


def test_decide_join_room_seats_the_first_joiner_as_the_opponent_and_asks_the_caller_to_start_the_game():
    rooms = RoomRegistry()
    room = rooms.create("alice")
    router, _loop, _rooms, _connections = _router(rooms=rooms)

    decision = router.decide_join_room("bob", room.room_id)

    assert decision.ack.accepted is True
    assert decision.ack.role == "opponent"
    assert decision.start_room is room
    assert decision.spectator_snapshot is None


def test_decide_join_room_makes_a_third_joiner_a_spectator_with_a_snapshot_once_the_game_is_running():
    rating_store = _rating_store("alice", "bob", "carol")
    rooms = RoomRegistry()
    room = rooms.create("alice")
    rooms.join(room.room_id, "bob")
    router, loop, _rooms, _connections = _router(rating_store=rating_store, rooms=rooms)
    _seat_alice_and_bob(loop, rating_store, game_id=room.room_id)

    decision = router.decide_join_room("carol", room.room_id)

    assert decision.ack.accepted is True
    assert decision.ack.role == "spectator"
    assert decision.start_room is None
    assert decision.spectator_snapshot is not None
    assert "board_width" in decision.spectator_snapshot


def test_decide_join_room_gives_a_spectator_no_snapshot_before_the_game_has_actually_started():
    rooms = RoomRegistry()
    room = rooms.create("alice")
    rooms.join(room.room_id, "bob")
    router, _loop, _rooms, _connections = _router(rooms=rooms)

    decision = router.decide_join_room("carol", room.room_id)

    assert decision.ack.accepted is True
    assert decision.ack.role == "spectator"
    assert decision.spectator_snapshot is None


# ---- decide_identify ----


def test_decide_identify_for_a_username_with_no_active_game_is_ack_only():
    router, _loop, _rooms, _connections = _router()

    decision = router.decide_identify("alice")

    assert decision.ack.accepted is True
    assert decision.seat is None
    assert decision.snapshot is None


def test_decide_identify_for_a_seated_player_resends_seat_and_snapshot():
    rating_store = _rating_store()
    router, loop, _rooms, _connections = _router(rating_store=rating_store)
    _seat_alice_and_bob(loop, rating_store)

    decision = router.decide_identify("alice")

    assert decision.ack.accepted is True
    assert decision.seat == WHITE
    assert decision.snapshot is not None


def test_decide_identify_reconnects_a_disconnected_seat():
    rating_store = _rating_store()
    router, loop, _rooms, _connections = _router(rating_store=rating_store)
    session = _seat_alice_and_bob(loop, rating_store)
    session.mark_disconnected(WHITE)

    decision = router.decide_identify("alice")

    assert decision.seat == WHITE
    assert session.is_disconnected(WHITE) is False


def test_decide_identify_for_an_already_tracked_spectator_resends_a_snapshot_with_no_seat():
    rating_store = _rating_store("alice", "bob", "carol")
    router, loop, _rooms, _connections = _router(rating_store=rating_store)
    _seat_alice_and_bob(loop, rating_store)
    loop.get("play-1").spectator_usernames.add("carol")

    decision = router.decide_identify("carol")

    assert decision.ack.accepted is True
    assert decision.seat is None
    assert decision.snapshot is not None


# The spectator self-heal case this pass adds: a REST-joined spectator
# (services/api_gateway/main.py's handle_join_room) whose room membership
# already lives in the cross-process RedisRoomRegistry, but who has never
# reached this shard's own spectator_usernames yet, since a spectator join
# publishes no event of its own (see server/router.py's decide_identify
# docstring). Also proves the self-heal actually mutates spectator_usernames,
# not just this one response - a later broadcast must reach them too.
def test_decide_identify_self_heals_a_spectator_known_only_to_remote_rooms():
    rating_store = _rating_store("alice", "bob", "carol")
    room = Room(room_id="room-1", creator="alice", opponent="bob", spectators={"carol"})
    remote_rooms = _FakeRemoteRooms({"carol": room})
    router, loop, _rooms, _connections = _router(rating_store=rating_store, remote_rooms=remote_rooms)
    _seat_alice_and_bob(loop, rating_store, game_id="room-1")

    decision = router.decide_identify("carol")

    assert decision.ack.accepted is True
    assert decision.seat is None
    assert decision.snapshot is not None
    assert "carol" in loop.get("room-1").spectator_usernames


# remote_rooms knows about the room, but this shard doesn't host its game
# (wrong shard, or the game hasn't started here) - self.loop.get(room_id) is
# None, so there is nothing to heal into; falls back to ack-only rather than
# raising.
def test_decide_identify_does_not_crash_when_remote_rooms_names_a_room_this_shard_does_not_host():
    remote_rooms = _FakeRemoteRooms({"carol": Room(room_id="room-1", creator="alice", opponent="bob", spectators={"carol"})})
    router, _loop, _rooms, _connections = _router(remote_rooms=remote_rooms)

    decision = router.decide_identify("carol")

    assert decision.ack.accepted is True
    assert decision.seat is None
    assert decision.snapshot is None


# remote_rooms omitted entirely (default None, the bare-metal/single-process
# case) - decide_identify must not even attempt the lookup, and behaves
# exactly as it did before this pass.
def test_decide_identify_without_remote_rooms_configured_is_unaffected():
    router, _loop, _rooms, _connections = _router()

    decision = router.decide_identify("carol")

    assert decision.ack.accepted is True
    assert decision.seat is None
    assert decision.snapshot is None


# ---- decide_cancel_room ----


def test_decide_cancel_room_succeeds_for_the_creator_of_a_pending_room():
    rooms = RoomRegistry()
    rooms.create("alice")
    router, _loop, _rooms, _connections = _router(rooms=rooms)

    ack = router.decide_cancel_room("alice")

    assert ack.accepted is True
    assert rooms.room_for_username("alice") is None


def test_decide_cancel_room_rejects_a_username_not_in_any_room():
    router, _loop, _rooms, _connections = _router()

    ack = router.decide_cancel_room("alice")

    assert ack.accepted is False
    assert ack.reason == "not_in_a_room"


# ---- decide_game_command ----


def test_decide_game_command_rejects_a_username_not_seated_in_any_game():
    router, _loop, _rooms, _connections = _router()
    message = build_move(WHITE, Position(0, 0), Position(0, 2))

    ack = router.decide_game_command("alice", message)

    assert ack.accepted is False
    assert ack.reason == "not_in_game"


def test_decide_game_command_rejects_a_move_claiming_the_wrong_seats_color():
    rating_store = _rating_store()
    router, loop, _rooms, _connections = _router(rating_store=rating_store)
    _seat_alice_and_bob(loop, rating_store)
    message = build_move(BLACK, Position(0, 0), Position(0, 2))  # alice is actually seated WHITE

    ack = router.decide_game_command("alice", message)

    assert ack.accepted is False
    assert ack.reason == "wrong_seat"


# A structurally-valid MoveMessage (satisfies protocol/registry.py's own
# top-level dataclass construction - source is *a* dict) whose source
# carries none of the "row"/"col" keys command_from_message's own
# position_from_json needs - see server/router.py's own comment on why
# this must be a normal rejected Ack, not a KeyError left to propagate out
# of routing and kill this connection's whole receive loop.
def test_decide_game_command_rejects_a_move_with_a_malformed_source():
    rating_store = _rating_store()
    router, loop, _rooms, _connections = _router(rating_store=rating_store)
    _seat_alice_and_bob(loop, rating_store)
    message = MoveMessage(color=WHITE, source={}, destination={"row": 0, "col": 2})

    ack = router.decide_game_command("alice", message)

    assert ack.accepted is False
    assert ack.reason == "malformed_command"


def test_decide_game_command_accepts_a_legal_move_from_the_correct_seat():
    rating_store = _rating_store()
    router, loop, _rooms, _connections = _router(rating_store=rating_store)
    _seat_alice_and_bob(loop, rating_store)
    message = build_move(WHITE, Position(0, 0), Position(0, 2))

    ack = router.decide_game_command("alice", message)

    assert ack.accepted is True


def test_decide_game_command_accepts_a_legal_jump_from_the_correct_seat():
    rating_store = _rating_store()
    router, loop, _rooms, _connections = _router(rating_store=rating_store)
    _seat_alice_and_bob(loop, rating_store)
    message = build_jump(WHITE, Position(0, 0))

    ack = router.decide_game_command("alice", message)

    assert ack.accepted is True


# ---- decide_disconnect ----


def test_decide_disconnect_marks_a_seated_players_seat_disconnected():
    rating_store = _rating_store()
    router, loop, _rooms, _connections = _router(rating_store=rating_store)
    session = _seat_alice_and_bob(loop, rating_store)

    router.decide_disconnect("alice")

    assert session.is_disconnected(WHITE) is True
    assert session.is_disconnected(BLACK) is False


def test_decide_disconnect_drops_a_spectator_without_touching_the_game():
    rating_store = _rating_store("alice", "bob", "carol")
    router, loop, _rooms, _connections = _router(rating_store=rating_store)
    session = _seat_alice_and_bob(loop, rating_store)
    game = loop.get("play-1")
    game.spectator_usernames.add("carol")

    router.decide_disconnect("carol")

    assert "carol" not in game.spectator_usernames
    assert session.is_disconnected(WHITE) is False
    assert session.is_disconnected(BLACK) is False


def test_decide_disconnect_cancels_a_still_pending_room_created_by_this_username():
    rooms = RoomRegistry()
    room = rooms.create("alice")
    router, _loop, _rooms, _connections = _router(rooms=rooms)

    router.decide_disconnect("alice")

    assert rooms.room_for_username("alice") is None


def test_decide_disconnect_removes_a_still_queued_username_from_matchmaking():
    router, loop, _rooms, _connections = _router()
    loop.matchmaking.enqueue("alice", rating=1200)

    router.decide_disconnect("alice")

    assert loop.matchmaking.is_waiting("alice") is False


def test_decide_disconnect_does_not_cancel_a_room_whose_game_already_started():
    rating_store = _rating_store()
    rooms = RoomRegistry()
    room = rooms.create("alice")
    rooms.join(room.room_id, "bob")
    router, loop, _rooms, _connections = _router(rating_store=rating_store, rooms=rooms)
    _seat_alice_and_bob(loop, rating_store, game_id=room.room_id)

    router.decide_disconnect("alice")

    assert rooms.room_for_username("alice") is room
