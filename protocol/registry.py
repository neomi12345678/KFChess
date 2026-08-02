"""Type-tag -> message-class lookup for message_from_dict, the one place
that knows the mapping so a caller decoding an incoming dict never re-lists
each message's own fields by hand the way client/network_message_adapter.py's
factories used to.

Decentralized rather than one central table: lobby_messages.py and
game_messages.py each call register() on their own classes as they're
defined, so adding a new message family never means also touching a third
file that lists every class by hand.

message_to_dict/encode_json_message are the encode-direction counterparts -
every one of this project's own frozen wire dataclasses (both directions:
a client's LoginMessage/MoveMessage/... and the server's LoginAckMessage/
SeatMessage/...) round-trips through this same pair of functions, the same
way message_from_dict/decode_json_message already are the one decode path
for both. server/connections.py's ConnectionRegistry.send is the other
caller of message_to_dict - see its own docstring for why outgoing traffic
still funnels through there rather than each site calling json.dumps itself.
"""

import json
import typing
from dataclasses import asdict, fields, is_dataclass
from enum import Enum
from typing import Dict, Optional, Type, TypeVar

_MESSAGE_CLASSES: Dict[str, Type] = {}

T = TypeVar("T")


def register(type_tag: str):
    def decorator(cls: Type[T]) -> Type[T]:
        _MESSAGE_CLASSES[type_tag] = cls
        return cls

    return decorator


# The Enum a field is (or, for an Optional[SomeEnum] field like
# JoinRoomAckMessage.role, is allowed to be) - None for anything else
# (str, int, another dataclass's own field, ...). Used by message_from_dict
# below so a decoded field actually comes back as that Enum member, not the
# plain str value that happens to compare equal to it (Role/Reason/etc. are
# all `str, Enum` subclasses - see protocol/types.py) - real today only
# because nothing has ever needed isinstance(x.role, Role) to hold after a
# real decode, not because the field types don't say otherwise.
def _enum_type(field_type) -> Optional[Type[Enum]]:
    if isinstance(field_type, type) and issubclass(field_type, Enum):
        return field_type
    if typing.get_origin(field_type) is typing.Union:
        for arg in typing.get_args(field_type):
            if isinstance(arg, type) and issubclass(arg, Enum):
                return arg
    return None


# Reconstructs the dataclass a wire dict's own "type" says it is, or None
# for a type this table doesn't recognize - covers both the per-tick
# snapshot broadcast (which carries no "type" at all, see
# snapshot_codec.py's snapshot_to_json) and any other payload that isn't
# one of the registered messages, the same "unknown is a no-op" contract
# client/network_message_adapter.py's NetworkMessageAdapter.apply already
# has for a message type it has no factory for. Filters payload down to the
# dataclass's own field names first, rather than passing it through as
# **payload, so an extra key (e.g. a stale "clock_ms" from some other
# caller) is silently ignored instead of raising a TypeError here.
def message_from_dict(payload: Dict[str, object]) -> Optional[object]:
    # payload is only actually guaranteed to be a dict once it's crossed
    # this boundary successfully - valid JSON can just as easily decode to
    # a bare scalar or list (json.loads('null')/('42')/('[1,2,3]')), which
    # has no .get at all. Treated the same as an unrecognized type tag
    # rather than left to raise AttributeError here: the one declared
    # gatekeeper for this wire boundary (see server/ws_server.py's
    # _handle_message) should cover every malformed shape, not just a
    # missing/mistyped field inside an otherwise-well-formed dict.
    if not isinstance(payload, dict):
        return None
    type_tag = payload.get("type")
    if not isinstance(type_tag, str):
        return None
    cls = _MESSAGE_CLASSES.get(type_tag)
    if cls is None:
        return None
    kwargs = {}
    for field in fields(cls):
        if field.name not in payload:
            continue
        value = payload[field.name]
        if value is not None:
            enum_type = _enum_type(field.type)
            if enum_type is not None:
                value = enum_type(value)
        kwargs[field.name] = value
    return cls(**kwargs)


# Plain-dict form of any registered wire dataclass - a field only ever has a
# default (None) when that message genuinely omits it sometimes (see each
# message's own docstring), so stripping None fields here is what keeps a
# message's wire shape unchanged from a hand-written dict with that key left
# out entirely, not present-but-null.
def message_to_dict(message) -> dict:
    return {key: value for key, value in asdict(message).items() if value is not None}


def encode_json_message(message) -> str:
    return json.dumps(message_to_dict(message))


# The one-step decode a caller reaches for at the actual network boundary
# (see server/ws_server.py's _handle_message). client/network_client.py's
# own decode_incoming decodes the exact same wire text but can't call this
# directly: it needs the parsed payload dict itself first, to tell a
# snapshot broadcast apart from a registered message (see
# protocol/snapshot_codec.py's is_snapshot_payload) before message_from_dict
# ever runs - so it calls json.loads/message_from_dict itself, in the same
# order this function does, rather than through this wrapper.
# message_from_dict alone is also what client/network_message_adapter.py
# uses, since it already has a plain dict off client/network_client.py's own
# queue rather than raw wire text.
def decode_json_message(raw: str) -> Optional[object]:
    return message_from_dict(json.loads(raw))
