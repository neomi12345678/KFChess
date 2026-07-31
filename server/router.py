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
    IdentifyAckMessage,
    JoinRoomAckMessage,
    LoginAckMessage,
    PlayAckMessage,
)
from protocol.types import Reason, Role
from server.game_loop import GameLoop, full_broadcast_payload
from server.interfaces import MessageSender, RatingRepository
from server.participant import ParticipantState, participant_state
from server.command_translation import MOVE, command_from_message
from server.rooms import Room, RoomError, RoomLookupProtocol, RoomRegistry

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


@dataclass(frozen=True)
class IdentifyDecision:
    ack: IdentifyAckMessage
    # Both set together, only when username is currently seated in a live
    # game - see decide_identify's own docstring for why this is
    # unconditional (not just on an actual disconnect/reconnect).
    seat: Optional[str] = None
    snapshot: Optional[dict] = None


class CommandRouter:
    def __init__(
        self,
        rooms: RoomRegistry,
        game_loop: GameLoop,
        rating_store: RatingRepository,
        connections: MessageSender,
        # Overridable so server/main.py can hand in a Redis-backed,
        # read-only reference to the standalone API Gateway's own room
        # registry (see server/redis/rooms.py's RedisRoomRegistry) - only
        # ever used by decide_identify, to recognize a spectator whose
        # room-membership already exists in that cross-process registry but
        # whose GameLoop.spectator_usernames entry (this shard's own,
        # self._rooms above never sees it) doesn't yet. None (the default)
        # is a no-op - every existing caller/test that omits it keeps
        # today's behavior unchanged (self._rooms already covers the
        # bare-metal, single-process case fully on its own).
        remote_rooms: Optional[RoomLookupProtocol] = None,
    ):
        self._rooms = rooms
        self._loop = game_loop
        self._rating_store = rating_store
        self._connections = connections
        self._remote_rooms = remote_rooms

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
        # restart (see server/sqlite/rooms.py's RoomStore) has no GameSession to
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

    # Called once server/ws_server.py's _handle_identify has already
    # registered the websocket under this username - the IDENTIFY
    # counterpart to decide_login, reached when a client authenticated over
    # REST instead (see services/api_gateway/main.py's POST /login). Only
    # replicates decide_login's first branch (reconnect into an
    # already-live GameSession) - never its second (a room surviving a
    # server restart, which needs "is the other participant currently
    # connected," a notion that doesn't survive login moving off the
    # persistent websocket - see this project's own design notes on why
    # that branch is staying on LoginMessage for now) or its third (an
    # ordinary fresh login has nothing left to do here; REST already
    # returned rating/reconnected state). Always accepted - this is
    # registration, not a decision that can be rejected. That's still true
    # of every call this method actually receives: server/ws_server.py's
    # _handle_identify now verifies the IdentifyMessage's session token
    # (see server/accounts.py's verify_session_token) before calling this
    # at all, and rejects on its own, one layer up, without ever reaching
    # here - so "always accepted" describes this method's own contract on a
    # pre-verified username, not a claim that no IDENTIFY can ever be
    # rejected.
    #
    # Unlike decide_login, this always re-sends seat/snapshot when the
    # username is currently seated - not just when its seat was actually
    # marked disconnected. Reason: a standalone WS Gateway
    # (services/ws_gateway/main.py) races GameLoop._start_game's own
    # one-shot SeatMessage broadcast - both react to the same
    # game.allocated NATS event independently, and IDENTIFY reaching this
    # shard *after* _start_game already ran (and already tried to send
    # SeatMessage to a username ConnectionRegistry didn't know about yet)
    # would otherwise silently strand that client seatless forever, since
    # SeatMessage is never persisted or retried anywhere else. Harmless to
    # resend to an already-synced client (the same "just tell it again"
    # doesn't hurt, see JoinRoomDecision's own spectator_snapshot for the
    # same idea).
    #
    # Also the spectator-flow counterpart to server/ws_server.py's own
    # bare-metal _handle_join_room (which adds a spectator to
    # spectator_usernames the instant they join, in-process, synchronously):
    # a spectator who joined via the standalone REST API Gateway
    # (services/api_gateway/main.py's handle_join_room) never sends any
    # message to this shard *at all* until this IDENTIFY - their room
    # membership already lives durably in the cross-process
    # RedisRoomRegistry (self._remote_rooms below), not in this shard's own
    # spectator_usernames yet. No race to close here the way the SeatMessage
    # one above needed two fixes for: there is no push event a spectator's
    # own IDENTIFY could race against (see services/api_gateway/main.py's
    # handle_join_room, deliberately publishing nothing for a spectator
    # join) - this single synchronous read, performed exactly once, exactly
    # when needed, is the only mechanism.
    def decide_identify(self, username: str) -> IdentifyDecision:
        game = self._loop.active_game_for(username)
        if game is None and self._remote_rooms is not None:
            room = self._remote_rooms.room_for_username(username)
            if room is not None and username in room.spectators:
                candidate = self._loop.get(room.room_id)
                if candidate is not None:
                    candidate.spectator_usernames.add(username)
                    game = candidate

        if game is None:
            return IdentifyDecision(ack=IdentifyAckMessage(accepted=True))

        seat = game.session.seat_for_username(username)
        if seat is None:
            # No seat - a spectator (already tracked, or just self-healed
            # above). Still worth a snapshot, same "don't make them wait for
            # the next tick" reasoning JoinRoomDecision's own
            # spectator_snapshot already has for the bare-metal join path.
            return IdentifyDecision(ack=IdentifyAckMessage(accepted=True), snapshot=full_broadcast_payload(game.session))

        if game.session.is_disconnected(seat):
            game.session.mark_reconnected(seat)

        return IdentifyDecision(
            ack=IdentifyAckMessage(accepted=True), seat=seat, snapshot=full_broadcast_payload(game.session)
        )

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

        # source/destination are typed as a plain dict on the wire message
        # itself (protocol/game_messages.py) - any dict, even {} , already
        # satisfies that dataclass's own construction, so a client sending
        # e.g. {"source": {}} sails past protocol/registry.py's top-level
        # gatekeeper untouched. command_from_message's own position_from_json
        # is what actually needs "row"/"col" to be there - catching its
        # failure here, rather than letting a bare KeyError/TypeError
        # propagate out of routing entirely, is what keeps this one
        # malformed command a normal rejected Ack instead of killing this
        # connection's whole receive loop for every other message on it too.
        try:
            command = command_from_message(message)
        except (KeyError, TypeError):
            return AckMessage(accepted=False, reason=Reason.MALFORMED_COMMAND)

        # position_from_json itself doesn't raise for this shape - a wire
        # payload with "source"/"destination" explicitly present but null
        # (as opposed to missing entirely, which the except above already
        # catches via message_from_dict's own required-argument TypeError)
        # decodes cleanly into a None Position, sailing past the try/except
        # above untouched. Left unchecked, that None would only fail once it
        # reaches board.is_in_bounds() several calls into apply_command
        # (AttributeError: 'NoneType' object has no attribute 'row'), outside
        # this method's own guard - source is required for both MOVE and
        # JUMP, destination only for MOVE (JumpMessage carries none at all,
        # so command.destination is always None there by construction, not a
        # malformed one).
        if command.source is None or (command.kind == MOVE and command.destination is None):
            return AckMessage(accepted=False, reason=Reason.MALFORMED_COMMAND)

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
