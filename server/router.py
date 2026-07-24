"""The lobby/game command router, split out of server/ws_server.py's
GameServer so the actual routing *decisions* (is this PLAY allowed right
now, does this JOIN_ROOM seat an opponent or a spectator, is this move
legal for the seat that sent it, what does a dropped connection mean for
matchmaking/its game/its room) can be exercised with plain Python values
- a username, an already-decoded wire message (protocol/lobby_messages.py's/
protocol/game_messages.py's own registered dataclasses), a room id - and
none of this class's own methods are async or ever touch a websocket, JSON,
or a raw dict: every method here takes typed arguments and returns a typed
decision (one of protocol/lobby_messages.py's or protocol/game_messages.py's
ack dataclasses, or a small decision dataclass bundling one with what the
caller must still do asynchronously - send it, and/or start a room's game),
except decide_disconnect, which has no ack to send back and so just performs
its mutations directly (see its own docstring).

server/ws_server.py stays the async half: accepting connections, decoding
raw wire text into the typed values this class expects (see its own
_handle_message), calling this class, then performing the actual send (and
any follow-up async action a decision calls for) - the same split their
own ConnectionLifecycle/ClientMessageRouter documented in their own
project have.
"""

import logging
from dataclasses import dataclass
from typing import Optional, Union

from model.piece import BLACK, WHITE
from protocol.game_messages import AckMessage, JumpMessage, MoveMessage
from protocol.lobby_messages import (
    CancelRoomAckMessage,
    CreateRoomAckMessage,
    JoinRoomAckMessage,
    LoginAckMessage,
    PlayAckMessage,
)
from protocol.types import Reason, Role
from server.game_loop import GameLoop, full_broadcast_payload
from server.interfaces import MessageSender, RatingRepository
from server.participant import ParticipantState, participant_state
from server.command_translation import command_from_message
from server.rooms import Room, RoomError, RoomRegistry

_logger = logging.getLogger(__name__)

# The wire-ready reason code for each busy ParticipantState - the exact
# strings tests/integration/test_server_ws.py already asserts on, carried
# over unchanged from GameServer's own former _busy_reason.
_BUSY_REASON_BY_STATE = {
    ParticipantState.IN_ROOM: Reason.ALREADY_IN_GAME,
    ParticipantState.SEARCHING: Reason.ALREADY_QUEUED,
}


@dataclass(frozen=True)
class LoginDecision:
    ack: LoginAckMessage
    # Set only when this login just reunited a room's second seat with an
    # opponent who was already back online after a server restart - see
    # decide_login's own comment. server/ws_server.py awaits
    # GameLoop.start_room_game(start_room) when this is set, since starting
    # a game means broadcasting SeatMessages, an async send this class
    # never performs itself.
    start_room: Optional[Room] = None


@dataclass(frozen=True)
class JoinRoomDecision:
    ack: JoinRoomAckMessage
    start_room: Optional[Room] = None
    # A plain dict (see protocol/snapshot_codec.py) rather than another
    # typed message - set only when a spectator joins a game already in
    # progress, so they see the board as it stands right now instead of
    # nothing until the next tick's broadcast.
    spectator_snapshot: Optional[dict] = None


class CommandRouter:
    def __init__(
        self,
        rooms: RoomRegistry,
        game_loop: GameLoop,
        rating_store: RatingRepository,
        connections: MessageSender,
    ):
        self._rooms = rooms
        self._loop = game_loop
        self._rating_store = rating_store
        self._connections = connections

    # Called once server/ws_server.py's _handle_login has already verified
    # the password and registered the websocket under this username - the
    # one part of login that stays outside this class, since checking a
    # password is a slow (deliberately, see server/accounts.py) executor
    # call, not a routing decision.
    def decide_login(self, username: str, rating: int) -> LoginDecision:
        game = self._loop.active_game_for(username)
        seat = game.session.seat_for_username(username) if game is not None else None
        if seat is not None and game.session.is_disconnected(seat):
            game.session.mark_reconnected(seat)
            return LoginDecision(
                ack=LoginAckMessage(accepted=True, username=username, rating=rating, reconnected=True, color=seat)
            )

        # A room whose opponent seat was already filled before a server
        # restart (see server/rooms.py's RoomStore) has no GameSession to
        # reconnect into above - board state itself is never persisted.
        # Instead, once both the creator and opponent are back online, a
        # fresh game starts for them in the same room, the same way a
        # freshly filled opponent seat already does.
        room = self._rooms.room_for_username(username)
        if room is not None and self._loop.get(room.room_id) is None and username in (room.creator, room.opponent):
            other_username = room.opponent if username == room.creator else room.creator
            seat = WHITE if username == room.creator else BLACK
            if other_username is not None and self._connections.get(other_username) is not None:
                return LoginDecision(
                    ack=LoginAckMessage(
                        accepted=True, username=username, rating=rating, reconnected=True, color=seat
                    ),
                    start_room=room,
                )
            return LoginDecision(
                ack=LoginAckMessage(accepted=True, username=username, rating=rating, resuming_room_id=room.room_id)
            )

        return LoginDecision(ack=LoginAckMessage(accepted=True, username=username, rating=rating))

    def decide_play(self, username: str) -> PlayAckMessage:
        reason = self._busy_reason(username)
        if reason is not None:
            return PlayAckMessage(accepted=False, reason=reason)

        rating = self._rating_store.rating_for(username)
        self._loop.matchmaking.enqueue(username, rating)
        return PlayAckMessage(accepted=True, reason=Reason.QUEUED)

    def decide_create_room(self, username: str) -> CreateRoomAckMessage:
        reason = self._busy_reason(username)
        if reason is not None:
            return CreateRoomAckMessage(accepted=False, reason=reason)

        room = self._rooms.create(username)
        _logger.info("'%s' created room %s", username, room.room_id)
        return CreateRoomAckMessage(accepted=True, room_id=room.room_id)

    def decide_join_room(self, username: str, room_id: str) -> JoinRoomDecision:
        reason = self._busy_reason(username)
        if reason is not None:
            return JoinRoomDecision(ack=JoinRoomAckMessage(accepted=False, reason=reason))

        try:
            room = self._rooms.join(room_id, username)
        except RoomError as error:
            return JoinRoomDecision(ack=JoinRoomAckMessage(accepted=False, reason=str(error)))

        role = Role.OPPONENT if room.opponent == username else Role.SPECTATOR
        _logger.info("'%s' joined room %s as %s", username, room_id, role)
        ack = JoinRoomAckMessage(accepted=True, room_id=room_id, role=role)

        if role == Role.OPPONENT:
            return JoinRoomDecision(ack=ack, start_room=room)

        game = self._loop.get(room_id)
        if game is None:
            return JoinRoomDecision(ack=ack)

        game.spectator_usernames.add(username)
        spectator_snapshot = full_broadcast_payload(game.session)
        return JoinRoomDecision(ack=ack, spectator_snapshot=spectator_snapshot)

    def decide_cancel_room(self, username: str) -> CancelRoomAckMessage:
        try:
            self._rooms.cancel(username)
        except RoomError as error:
            return CancelRoomAckMessage(accepted=False, reason=str(error))

        _logger.info("'%s' cancelled their room", username)
        return CancelRoomAckMessage(accepted=True)

    def decide_game_command(self, username: str, message: Union[MoveMessage, JumpMessage]) -> AckMessage:
        game = self._loop.active_game_for(username)
        seat = game.session.seat_for_username(username) if game is not None else None
        if seat is None:
            return AckMessage(accepted=False, reason=Reason.NOT_IN_GAME)

        # A connection may only move the color it was seated as - the
        # message's own color is otherwise just a client-asserted claim, not
        # something GameEngine checks (see server/session.py).
        if message.color != seat:
            return AckMessage(accepted=False, reason=Reason.WRONG_SEAT)

        command = command_from_message(message)
        result = game.session.apply_command(command)
        return AckMessage(accepted=result.is_accepted, reason=result.reason)

    # Shared by decide_play/decide_create_room/decide_join_room - a
    # connection may only ever be committed to one thing at a time (queued,
    # in a room, or seated/spectating an active game), across both the PLAY
    # and room tracks together, not per-track. None means free to start
    # something new.
    def _busy_reason(self, username: str) -> Optional[str]:
        state = participant_state(username, self._loop, self._rooms)
        if state is None:
            return None
        return _BUSY_REASON_BY_STATE[state]

    # What "this username's connection just dropped" means across matchmaking/
    # game/room state - the one non-login/lobby-command decision this router
    # makes, called from server/ws_server.py's _handle_connection `finally`
    # block instead of living inline there. Kept here rather than in
    # GameServer for the same reason every other decision above is: no part
    # of it is async or touches a websocket, so it's exercisable with plain
    # Python values (see tests/unit/test_router.py) instead of only through a
    # real socket at the integration-test level. Mutates state directly
    # (matchmaking removal, marking a seat disconnected, dropping a
    # spectator, cancelling a still-pending room) rather than returning a
    # decision for the caller to apply - there's no ack to send back for a
    # disconnect, unlike decide_play/decide_create_room/decide_join_room,
    # which mutate matchmaking/rooms too but still owe the caller a reply.
    def decide_disconnect(self, username: str) -> None:
        self._loop.matchmaking.remove(username)

        game = self._loop.active_game_for(username)
        if game is not None:
            seat = game.session.seat_for_username(username)
            if seat is not None:
                game.session.mark_disconnected(seat)
            else:
                game.spectator_usernames.discard(username)
            return

        # Only a still-pending room (no opponent yet, so no game exists for
        # active_game_for to have found above) can be unwound outright on
        # disconnect - once a room's game has started, the seat's disconnect
        # grace handled above is what applies instead.
        room = self._rooms.room_for_username(username)
        if room is not None and room.is_pending:
            self._rooms.cancel(username)
