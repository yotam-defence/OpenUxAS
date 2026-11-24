"""Encode scenario messages / decode captured wire messages.

``pylmcp`` (which needs ``e3``) is imported lazily. When it is not importable
the decoder degrades to header-only records (``obj`` is ``None`` and the
payload hex is kept) so that raw comparison remains possible.
"""
import os
import sys

_PYLMCP = None


def _pylmcp():
    global _PYLMCP
    if _PYLMCP is None:
        try:
            import pylmcp  # noqa: F401
        except ImportError:
            parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if parent not in sys.path:
                sys.path.insert(0, parent)
            import pylmcp  # noqa: F401
        from pylmcp import Object
        from pylmcp.message import Message
        _PYLMCP = (Object, Message)
    return _PYLMCP


def encode_message(spec, default_entity_id: int) -> bytes:
    """Return the wire bytes (address$attrs$payload) for a MessageSpec."""
    if spec.hex is not None:
        return bytes.fromhex(spec.hex)
    Object, Message = _pylmcp()
    obj = Object(spec.lmcp["type"], **spec.lmcp.get("fields", {}))
    entity = (spec.source_entity_id if spec.source_entity_id is not None
              else default_entity_id)
    return Message(obj=obj, source_entity_id=entity,
                   source_service_id=spec.source_service_id).pack()


def jsonable(v):
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return repr(v)


def split_header(raw: bytes):
    address, attributes, payload = raw.split(b"$", 2)
    content_type, descriptor, group, eid, sid = attributes.split(b"|", 4)
    return {"address": address.decode(), "content_type": content_type.decode(),
            "descriptor": descriptor.decode(), "source_group": group.decode(),
            "source_entity_id": int(eid), "source_service_id": int(sid)}, payload


def decode_message(raw: bytes, step: int = 0, t: float = 0.0) -> dict:
    """Decode wire bytes into a capture record (see normalise.py)."""
    rec = {"raw_hex": raw.hex(), "step": step, "t": t, "obj": None,
           "decode_error": None}
    try:
        header, _ = split_header(raw)
    except ValueError as e:
        rec.update(address="", content_type="", descriptor="<malformed>",
                   source_group="", source_entity_id=-1, source_service_id=-1,
                   decode_error="malformed header: %s" % e)
        return rec
    rec.update(header)
    try:
        _, Message = _pylmcp()
        msg = Message.unpack(raw)
        rec["obj"] = jsonable(msg.obj.as_dict())
    except Exception as e:  # missing pylmcp/e3 or undecodable payload
        rec["decode_error"] = "%s: %s" % (type(e).__name__, e)
    return rec
