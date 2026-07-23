"""Type-tag -> message-class lookup for message_from_dict, the one place
that knows the mapping so a caller decoding an incoming dict never re-lists
each message's own fields by hand the way client/network_message_adapter.py's
factories used to.

Decentralized rather than one central table: lobby_messages.py and
game_messages.py each call register() on their own classes as they're
defined, so adding a new message family never means also touching a third
file that lists every class by hand.
"""

from dataclasses import fields
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
