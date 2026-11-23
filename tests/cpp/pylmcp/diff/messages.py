"""Message model shared by canonicaliser, comparators and runner.

``parse_envelope`` works on raw ZeroMQ frames without needing the LMCP
model, ``decode_frame`` additionally decodes the LMCP payload with pylmcp
(imported lazily).  Tests build ``DecodedMessage`` objects directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class DecodedMessage:
    type: str                        # full LMCP name, e.g. afrl.cmasi.KeyValuePair
    fields: Dict[str, Any] = field(default_factory=dict)
    address: str = ""
    content_type: str = "lmcp"
    source_group: str = ""
    source_entity_id: int = 0
    source_service_id: int = 0
    window: int = 0
    t_ms: float = 0.0
    side: str = ""


def parse_envelope(frame: bytes) -> Tuple[str, str, str, str, int, int]:
    """Return (address, content_type, descriptor, group, entity, service)."""
    address, attributes, _payload = frame.split(b"$", 2)
    ct, descriptor, group, ent, svc = attributes.split(b"|", 4)
    return (address.decode("utf-8"), ct.decode("utf-8"),
            descriptor.decode("utf-8"), group.decode("utf-8"),
            int(ent), int(svc))


def envelope_key(frame: bytes) -> Optional[tuple]:
    try:
        return parse_envelope(frame)
    except (ValueError, UnicodeDecodeError):
        return None


def decode_frame(frame: bytes, window: int = 0, t_ms: float = 0.0,
                 side: str = "") -> DecodedMessage:
    """Decode a raw frame into a DecodedMessage using pylmcp."""
    from pylmcp.message import Message  # lazy: pulls in the LMCP database
    msg = Message.unpack(frame)
    return DecodedMessage(
        type=msg.obj.object_class.full_name,
        fields=msg.obj.as_dict(),
        address=msg.address,
        content_type=msg.content_type,
        source_group=msg.source_group,
        source_entity_id=msg.source_entity_id,
        source_service_id=msg.source_service_id,
        window=window, t_ms=t_ms, side=side)
