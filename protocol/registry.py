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
from dataclasses import asdict, fields, is_dataclass
from typing import Dict, Optional, Type

_MESSAGE_CLASSES: Dict[str, Type] = {}


def register(type_tag: str):
    def decorator(cls: Type) -> Type:
        _MESSAGE_CLASSES[type_tag] = cls
        return cls

    return decorator


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
def message_from_dict(payload: dict) -> Optional[object]:
    cls = _MESSAGE_CLASSES.get(payload.get("type"))
    if cls is None:
        return None
    field_names = {f.name for f in fields(cls)}
    return cls(**{key: value for key, value in payload.items() if key in field_names})


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
# (see server/ws_server.py's _handle_message, client/network_client.py) -
# message_from_dict alone is still what client/network_message_adapter.py
# uses, since it already has a plain dict off client/network_client.py's own
# queue rather than raw wire text.
def decode_json_message(raw: str) -> Optional[object]:
    return message_from_dict(json.loads(raw))
