"""Replay messages over ZeroMQ and capture outbound LMCP messages.

zmq and pylmcp are imported lazily; the replay loop itself only needs a
``Transport`` (send bytes / poll bytes) and a ``decode`` callable, so it is
fully testable with a mock transport.
"""
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

PYLMCP_DIR = os.environ.get(
    "PYLMCP_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "cpp"))


def _pylmcp():
    """Lazily import pylmcp (needs the e3 package, like tests/cpp)."""
    if PYLMCP_DIR not in sys.path:
        sys.path.insert(0, PYLMCP_DIR)
    import pylmcp
    import pylmcp.message
    return pylmcp


def _build_object(spec: Dict[str, Any]):
    pylmcp = _pylmcp()

    def conv(v):
        if isinstance(v, dict) and "class" in v:
            return _build_object(v)
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v
    fields = {k: conv(v) for k, v in spec.get("fields", {}).items()}
    obj = pylmcp.Object(spec["class"], **fields)
    for attr in obj.attributes:  # pylmcp cannot pack unset (None) values
        if obj.data[attr.name] is None:
            obj.data[attr.name] = _default(attr)
    return obj


def _default(attr):
    """Zero value for an unset attribute (nested objects stay None)."""
    if attr.is_array:
        if attr.is_static_array:
            return [_default_simple(attr)] * attr.min_array_length
        return []
    return _default_simple(attr)


def _default_simple(attr):
    t = attr.attr_type
    if t == "string":
        return ""
    if t == "bool":
        return False
    if t in ("real32", "real64"):
        return 0.0
    if t in attr.BASIC_TYPES:
        return 0
    from pylmcp.model.enum import EnumModel
    if isinstance(attr.model_db.types[t], EnumModel):
        return 0
    return None


def build_wire(step: Dict[str, Any], entity_id: int = 100,
               service_id: int = 0) -> Optional[bytes]:
    """Wire bytes for a replay step (None for pure delay steps)."""
    if "hex" in step:
        return bytes.fromhex(step["hex"])
    if "object" in step:
        _pylmcp()
        from pylmcp.message import Message
        obj = _build_object(step["object"])
        return Message(obj=obj, source_entity_id=entity_id,
                       source_service_id=service_id).pack()
    return None


def decode_wire(raw: bytes) -> Dict[str, Any]:
    """Decode a received wire message into a capture record (sans timing)."""
    _pylmcp()
    from pylmcp.message import Message
    m = Message.unpack(raw)
    return {"address": m.address, "descriptor": m.descriptor,
            "content_type": m.content_type, "source_group": m.source_group,
            "source_entity_id": m.source_entity_id,
            "source_service_id": m.source_service_id,
            "obj": m.obj.as_dict()}


class Transport:
    """Minimal interface the replay loop needs."""

    def send(self, data: bytes) -> None:
        raise NotImplementedError

    def poll(self, timeout_ms: int) -> Optional[bytes]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class ZmqTransport(Transport):
    """SUB (capture) + PUSH (replay) sockets against a PublishPull bridge."""

    def __init__(self, pub_addr: str, pull_addr: str):
        import zmq  # lazy
        self._zmq = zmq
        self.ctx = zmq.Context()
        self.sub = self.ctx.socket(zmq.SUB)
        self.sub.setsockopt(zmq.SUBSCRIBE, b"")
        self.sub.connect(pub_addr)
        self.push = self.ctx.socket(zmq.PUSH)
        self.push.connect(pull_addr)

    def send(self, data: bytes) -> None:
        self.push.send(data)

    def poll(self, timeout_ms: int) -> Optional[bytes]:
        if self.sub.poll(timeout_ms, self._zmq.POLLIN):
            return self.sub.recv()
        return None

    def close(self) -> None:
        self.sub.close(0)
        self.push.close(0)
        self.ctx.term()


def replay(scenario: Dict[str, Any], transport: Transport,
           decode: Callable[[bytes], Dict[str, Any]] = decode_wire,
           wire: Callable[[Dict[str, Any]], Optional[bytes]] = build_wire,
           clock: Callable[[], float] = time.monotonic) -> List[Dict[str, Any]]:
    """Replay the scenario steps and return capture records.

    Each step first waits ``delay_ms`` (while capturing), then sends its
    message. ``phase`` of a captured record is the number of steps already
    sent when it arrived (0 before the first send). The capture window ends
    ``capture.tail_ms`` after the last step. ``startup_settle_ms`` is
    spent before replay starts so SUB/PUSH connections are established;
    anything captured then is recorded with phase 0.
    """
    records: List[Dict[str, Any]] = []
    t0 = clock()
    state = {"phase": 0}

    def pump(duration_ms: float) -> None:
        end = clock() + duration_ms / 1000.0
        while True:
            left = int((end - clock()) * 1000)
            if left <= 0:
                break
            raw = transport.poll(min(left, 100))
            if raw is None:
                continue
            rec = decode(raw)
            rec["t_ms"] = int((clock() - t0) * 1000)
            rec["phase"] = state["phase"]
            records.append(rec)

    pump(scenario.get("startup_settle_ms", 0))
    for step in scenario["messages"]:
        pump(step.get("delay_ms", 0))
        data = wire(step)
        if data is not None:
            transport.send(data)
        state["phase"] += 1
    pump(scenario["capture"].get("tail_ms", 0))
    return records
