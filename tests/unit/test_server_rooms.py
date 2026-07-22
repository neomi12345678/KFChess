import pytest

from server.rooms import RoomError, RoomRegistry, RoomStore


def test_create_returns_a_pending_room_with_no_opponent_yet():
    registry = RoomRegistry()

    room = registry.create("alice")

    assert room.creator == "alice"
    assert room.opponent is None
    assert room.spectators == set()
    assert room.is_pending is True


def test_create_gives_out_a_short_room_id():
    registry = RoomRegistry()

    room = registry.create("alice")

    assert isinstance(room.room_id, str)
    assert len(room.room_id) > 0


def test_create_ids_do_not_collide_across_rooms():
    registry = RoomRegistry()

    room_a = registry.create("alice")
    room_b = registry.create("bob")

    assert room_a.room_id != room_b.room_id


def test_create_rejects_a_username_already_in_a_room():
    registry = RoomRegistry()
    registry.create("alice")

    with pytest.raises(RoomError):
        registry.create("alice")


def test_join_fills_the_opponent_seat_and_ends_the_pending_state():
    registry = RoomRegistry()
    room = registry.create("alice")

    joined = registry.join(room.room_id, "bob")

    assert joined.opponent == "bob"
    assert joined.is_pending is False


def test_join_after_the_opponent_seat_is_filled_becomes_a_spectator():
    registry = RoomRegistry()
    room = registry.create("alice")
    registry.join(room.room_id, "bob")

    joined = registry.join(room.room_id, "carol")

    assert joined.opponent == "bob"
    assert joined.spectators == {"carol"}


def test_join_an_unknown_room_id_is_rejected():
    registry = RoomRegistry()

    with pytest.raises(RoomError):
        registry.join("no-such-room", "alice")


def test_join_rejects_a_username_already_in_a_room():
    registry = RoomRegistry()
    room = registry.create("alice")
    registry.create("bob")

    with pytest.raises(RoomError):
        registry.join(room.room_id, "bob")


def test_room_for_username_reflects_creator_opponent_and_spectator_membership():
    registry = RoomRegistry()
    room = registry.create("alice")
    registry.join(room.room_id, "bob")
    registry.join(room.room_id, "carol")

    assert registry.room_for_username("alice").room_id == room.room_id
    assert registry.room_for_username("bob").room_id == room.room_id
    assert registry.room_for_username("carol").room_id == room.room_id
    assert registry.room_for_username("nobody") is None


def test_cancel_by_the_creator_of_a_still_pending_room_removes_it():
    registry = RoomRegistry()
    room = registry.create("alice")

    registry.cancel("alice")

    assert registry.room_for_username("alice") is None
    with pytest.raises(RoomError):
        registry.join(room.room_id, "bob")


def test_cancel_by_a_non_creator_is_rejected():
    registry = RoomRegistry()
    room = registry.create("alice")
    registry.join(room.room_id, "bob")

    with pytest.raises(RoomError):
        registry.cancel("bob")


def test_cancel_after_the_room_has_started_is_rejected():
    registry = RoomRegistry()
    room = registry.create("alice")
    registry.join(room.room_id, "bob")

    with pytest.raises(RoomError):
        registry.cancel("alice")


def test_cancel_when_not_in_any_room_is_rejected():
    registry = RoomRegistry()

    with pytest.raises(RoomError):
        registry.cancel("nobody")


def test_close_frees_the_creator_opponent_and_every_spectator():
    registry = RoomRegistry()
    room = registry.create("alice")
    registry.join(room.room_id, "bob")
    registry.join(room.room_id, "carol")

    registry.close(room.room_id)

    assert registry.room_for_username("alice") is None
    assert registry.room_for_username("bob") is None
    assert registry.room_for_username("carol") is None


def test_close_of_an_already_gone_room_is_a_no_op():
    registry = RoomRegistry()

    registry.close("no-such-room")  # must not raise


# --- RoomStore, exercised directly ---


@pytest.fixture
def store():
    # ":memory:" - a real SQLite database, just an isolated, disposable one
    # per test (see RoomStore's own db_path docstring, mirroring
    # server/accounts.py's AccountStore fixture in test_server_accounts.py).
    store = RoomStore(":memory:")
    yield store
    store.close()


def test_load_all_on_a_fresh_store_is_empty(store):
    assert store.load_all() == []


def test_save_then_load_all_round_trips_a_pending_room(store):
    registry = RoomRegistry(store=store)
    room = registry.create("alice")

    [loaded] = store.load_all()

    assert loaded == {"room_id": room.room_id, "creator": "alice", "opponent": None, "spectators": set()}


def test_save_then_load_all_round_trips_opponent_and_spectators(store):
    registry = RoomRegistry(store=store)
    room = registry.create("alice")
    registry.join(room.room_id, "bob")
    registry.join(room.room_id, "carol")

    [loaded] = store.load_all()

    assert loaded == {"room_id": room.room_id, "creator": "alice", "opponent": "bob", "spectators": {"carol"}}


def test_save_is_an_upsert_not_a_duplicate_row(store):
    registry = RoomRegistry(store=store)
    room = registry.create("alice")

    registry.join(room.room_id, "bob")

    assert len(store.load_all()) == 1


def test_delete_removes_the_room_and_its_spectators(store):
    registry = RoomRegistry(store=store)
    room = registry.create("alice")
    registry.join(room.room_id, "bob")
    registry.join(room.room_id, "carol")

    registry.close(room.room_id)

    assert store.load_all() == []


# --- RoomRegistry reload, simulating a server restart against the same
# underlying store (a fresh process would instead reopen the same on-disk
# file - see server/main.py's ROOM_DB_PATH) ---


def test_a_new_registry_over_the_same_store_reconstructs_a_pending_room(store):
    RoomRegistry(store=store).create("alice")

    restarted = RoomRegistry(store=store)

    room = restarted.room_for_username("alice")
    assert room is not None
    assert room.creator == "alice"
    assert room.opponent is None
    assert room.is_pending is True


def test_a_new_registry_over_the_same_store_reconstructs_opponent_and_spectators():
    store = RoomStore(":memory:")
    first = RoomRegistry(store=store)
    room = first.create("alice")
    first.join(room.room_id, "bob")
    first.join(room.room_id, "carol")

    restarted = RoomRegistry(store=store)

    assert restarted.room_for_username("alice").room_id == room.room_id
    assert restarted.room_for_username("bob").room_id == room.room_id
    assert restarted.room_for_username("carol").room_id == room.room_id
    reloaded = restarted.room_for_username("alice")
    assert reloaded.opponent == "bob"
    assert reloaded.spectators == {"carol"}


def test_a_new_registry_over_the_same_store_does_not_see_a_cancelled_room():
    store = RoomStore(":memory:")
    first = RoomRegistry(store=store)
    room = first.create("alice")
    first.cancel("alice")

    restarted = RoomRegistry(store=store)

    assert restarted.room_for_username("alice") is None
    with pytest.raises(RoomError):
        restarted.join(room.room_id, "bob")


def test_a_new_registry_over_the_same_store_does_not_see_a_closed_room():
    store = RoomStore(":memory:")
    first = RoomRegistry(store=store)
    room = first.create("alice")
    first.join(room.room_id, "bob")
    first.close(room.room_id)

    restarted = RoomRegistry(store=store)

    assert restarted.room_for_username("alice") is None
    assert restarted.room_for_username("bob") is None
