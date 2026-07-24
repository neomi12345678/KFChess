"""participant_state() is the one place server/router.py's CommandRouter
learns whether a username is already busy, combining three independently-
owned registries (GameLoop's active games, RoomRegistry's pending rooms,
MatchmakingQueue's own waiting list) - its own docstring calls out that
IN_ROOM is checked before SEARCHING deliberately, since a username can, in
principle, be in both at once and IN_ROOM is meant to win. Exercised here
against real collaborators (a real GameLoop/RoomRegistry/MatchmakingQueue),
not fakes - all three are already cheap to construct directly.
"""

from boardio.board_parser import parse
from server.accounts import UserStore
from server.accounts_db import open_accounts_database
from server.connections import ConnectionRegistry
from server.game_loop import ActiveGame, GameLoop
from server.participant import ParticipantState, participant_state
from server.publisher import NetworkPublisher
from server.rating_store import RatingStore
from server.rooms import RoomRegistry
from server.session import GameSession

STARTING_BOARD = "wR . .\n. . .\n. . ."


def _rating_store():
    database = open_accounts_database(":memory:")
    user_store = UserStore(database)
    for username in ("alice", "bob"):
        user_store.login(username, "secret123")
    return RatingStore(database)


def _make_loop(rooms):
    return GameLoop(
        lambda: parse(STARTING_BOARD),
        _rating_store(),
        rooms,
        ConnectionRegistry(),
        matchmaking_timeout_ms=60_000,
        disconnect_grace_ms=20_000,
    )


def test_a_username_with_no_state_anywhere_is_free_to_start_something_new():
    loop = _make_loop(RoomRegistry())

    assert participant_state("alice", loop, RoomRegistry()) is None


def test_a_username_waiting_in_matchmaking_is_searching():
    loop = _make_loop(RoomRegistry())
    loop.matchmaking.enqueue("alice", rating=1200)

    assert participant_state("alice", loop, RoomRegistry()) is ParticipantState.SEARCHING


def test_a_username_in_a_still_pending_room_is_in_room():
    rooms = RoomRegistry()
    rooms.create("alice")
    loop = _make_loop(rooms)

    assert participant_state("alice", loop, rooms) is ParticipantState.IN_ROOM


def test_a_username_seated_in_an_active_game_is_in_room_even_with_no_room_at_all():
    rooms = RoomRegistry()
    loop = _make_loop(rooms)
    rating_store = _rating_store()
    session = GameSession(parse(STARTING_BOARD), rating_store, "alice", "bob")
    loop._games["play-1"] = ActiveGame(session=session, publisher=NetworkPublisher(session.bus))

    assert participant_state("alice", loop, rooms) is ParticipantState.IN_ROOM


def test_in_room_takes_precedence_over_searching_when_a_username_is_somehow_both():
    rooms = RoomRegistry()
    rooms.create("alice")
    loop = _make_loop(rooms)
    loop.matchmaking.enqueue("alice", rating=1200)

    assert participant_state("alice", loop, rooms) is ParticipantState.IN_ROOM
