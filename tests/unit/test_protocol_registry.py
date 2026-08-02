import pytest

from model.piece import WHITE
from model.position import Position
from protocol.game_messages import SeatMessage, build_move
from protocol.lobby_messages import JoinRoomAckMessage
from protocol.lobby_messages import LoginMessage
from protocol.registry import decode_json_message, encode_json_message
from protocol.snapshot_codec import position_to_json
from protocol.types import Role


def test_a_client_to_server_message_round_trips_through_the_same_codec_as_a_server_to_client_one():
    # The whole point: LoginMessage (client->server) and SeatMessage
    # (server->client) go through the exact same encode_json_message/
    # decode_json_message pair - unlike the old text-grammar wire format,
    # neither direction gets its own bespoke parser.
    login = LoginMessage(username="alice", password="secret123")
    seat = SeatMessage(color=WHITE)

    assert decode_json_message(encode_json_message(login)) == login
    assert decode_json_message(encode_json_message(seat)) == seat


def test_a_move_messages_positions_round_trip_as_plain_row_col_dicts():
    message = build_move(WHITE, Position(6, 4), Position(4, 4))

    decoded = decode_json_message(encode_json_message(message))

    assert decoded == message
    assert decoded.source == position_to_json(Position(6, 4))
    assert decoded.destination == position_to_json(Position(4, 4))


def test_encode_json_message_omits_fields_that_are_none():
    login_ack_json = encode_json_message(LoginMessage(username="alice", password="secret123"))

    assert '"username"' in login_ack_json
    assert "null" not in login_ack_json


def test_decode_json_message_returns_none_for_an_unrecognized_type():
    assert decode_json_message('{"type": "not_a_real_message"}') is None


# JoinRoomAckMessage.role is typed Optional[Role] - a real decode used to
# hand back the plain wire string ("spectator") instead, which happened to
# keep working everywhere only because Role is a `str, Enum` subclass that
# compares equal to its own value. isinstance(x.role, Role) would have
# silently failed on a decoded message even though the field's own type
# hint says it never should.
def test_decode_json_message_coerces_role_back_to_the_real_enum():
    message = JoinRoomAckMessage(accepted=True, room_id="abc123", role=Role.SPECTATOR)

    decoded = decode_json_message(encode_json_message(message))

    assert isinstance(decoded.role, Role)
    assert decoded.role == Role.SPECTATOR


# The exact exception type server/ws_server.py's own _handle_message (and
# server/router.py's own command_from_message call site) must catch
# alongside TypeError/KeyError: an Enum-typed field carrying a wire value
# that isn't one of that Enum's members raises ValueError, from
# _enum_type's own coercion, not TypeError/KeyError - those two gatekeepers
# used to only catch the latter pair, which would have let this one raise
# straight out of the connection's whole receive loop instead of coming
# back as a normal rejected/error response.
def test_decode_json_message_raises_value_error_for_an_unrecognized_enum_value():
    payload = '{"type": "join_room_ack", "accepted": true, "role": "not_a_real_role"}'

    with pytest.raises(ValueError):
        decode_json_message(payload)
