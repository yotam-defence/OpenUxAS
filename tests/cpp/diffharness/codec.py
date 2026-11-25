"""Wire encoding/decoding of LMCP messages (thin layer over pylmcp).

pylmcp (which needs the ``e3`` package) is imported lazily.  Everything
downstream of this module works on *plain records*: JSON-serialisable dicts

    {"t_ms": int, "address": str, "descriptor": str, "content_type": str,
     "source_group": str, "source_entity_id": int, "source_service_id": int,
     "obj": {"$type": "afrl.cmasi.KeyValuePair", "Key": "...", ...}}

so the normaliser, comparators and diff are testable without pylmcp.
"""
import base64
from typing import Any, Dict

from diffharness.scenario import ReplayStep

UNDECODABLE = "<undecodable>"


class MissingDependency(RuntimeError):
    pass


def _pylmcp():
    try:
        import pylmcp  # noqa: F401
        from pylmcp import Object
        from pylmcp.message import Message
    except ImportError as e:
        raise MissingDependency(
            "pylmcp could not be imported (%s). pylmcp lives in tests/cpp/ "
            "and requires the 'e3-core' package (pip install e3-core); make "
            "sure tests/cpp is on PYTHONPATH." % e)
    return Object, Message


def _build_value(Object, value: Any) -> Any:
    if isinstance(value, dict) and "$type" in value:
        kwargs = {k: _build_value(Object, v) for k, v in value.items()
                  if k != "$type"}
        return Object(value["$type"], **kwargs)
    if isinstance(value, list):
        return [_build_value(Object, v) for v in value]
    return value


def obj_to_plain(obj: Any) -> Any:
    """Convert a pylmcp Object (recursively) into plain JSON data."""
    if hasattr(obj, "object_class") and hasattr(obj, "data"):
        out = {"$type": obj.object_class.full_name}
        for k, v in obj.data.items():
            out[k] = obj_to_plain(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [obj_to_plain(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return base64.b64encode(bytes(obj)).decode("ascii")
    return obj


def encode_step(step: ReplayStep, default_entity_id: int) -> bytes:
    """Return the wire bytes for a replay step."""
    eid = (default_entity_id if step.source_entity_id is None
           else step.source_entity_id)
    sid = 0 if step.source_service_id is None else step.source_service_id
    if step.raw_b64 is not None:
        # Raw payload = packed LMCP object, we only add the transport frame.
        attrs = b"|".join([b"lmcp", step.address.encode(),
                           step.source_group.encode(),
                           str(eid).encode(), str(sid).encode()])
        return b"$".join([step.address.encode(), attrs, step.raw])
    Object, Message = _pylmcp()
    fields = {k: _build_value(Object, v) for k, v in step.fields.items()}
    obj = Object(step.type, **fields)
    msg = Message(obj=obj, source_entity_id=eid, source_service_id=sid,
                  source_group=step.source_group,
                  address=step.address)
    return msg.pack()


def decode_wire(raw: bytes, t_ms: int = 0) -> Dict[str, Any]:
    """Decode wire bytes received from a bridge into a plain record."""
    Object, Message = _pylmcp()
    try:
        m = Message.unpack(raw)
    except Exception as e:  # undecodable payload is data, not a crash
        head = raw.split(b"$", 1)[0].decode("utf-8", "replace")
        return {"t_ms": t_ms, "address": head, "descriptor": "",
                "content_type": "", "source_group": "",
                "source_entity_id": 0, "source_service_id": 0,
                "obj": {"$type": UNDECODABLE, "error": type(e).__name__,
                        "raw_b64": base64.b64encode(raw).decode("ascii")}}
    return {"t_ms": t_ms, "address": m.address, "descriptor": m.descriptor,
            "content_type": m.content_type, "source_group": m.source_group,
            "source_entity_id": m.source_entity_id,
            "source_service_id": m.source_service_id,
            "obj": obj_to_plain(m.obj)}
