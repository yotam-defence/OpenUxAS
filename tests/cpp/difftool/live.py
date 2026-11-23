"""Live ZeroMQ transport (lazy pylmcp/zmq imports)."""
import os
import sys
import threading
import time


class LiveError(Exception):
    pass


def _import_live():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)  # tests/cpp, which holds the pylmcp package
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import zmq  # noqa
    except ImportError as e:
        raise LiveError("live replay needs pyzmq: %s" % e)
    try:
        from pylmcp import Object  # noqa
        from pylmcp.message import Message  # noqa
    except ImportError as e:
        raise LiveError("live replay needs pylmcp and its deps (e3-core): %s" % e)
    return zmq, Object, Message


def _build(value, Object):
    """JSON -> pylmcp values.  A dict with a ``"_class"`` key is a nested object."""
    if isinstance(value, dict):
        d = dict(value)
        cls = d.pop("_class", None)
        if cls is None:
            raise LiveError("nested object needs a '_class' key: %r" % (value,))
        return Object(cls, **{k: _build(v, Object) for k, v in d.items()})
    if isinstance(value, list):
        return [_build(v, Object) for v in value]
    return value


def encode(msg, Object, Message):
    """Encode a scenario.Message to wire bytes."""
    obj = Object(msg.cls, **{k: _build(v, Object) for k, v in msg.fields.items()})
    kwargs = {}
    if msg.address is not None:
        kwargs["address"] = msg.address
    return Message(obj=obj, source_entity_id=msg.source_entity_id,
                   source_service_id=msg.source_service_id,
                   source_group=msg.source_group, **kwargs).pack()


def decode(raw, t_ms, Message):
    m = Message.unpack(raw)
    d = m.as_dict()
    return {"t_ms": t_ms, "address": d["address"], "descriptor": d["descriptor"],
            "content_type": d["content_type"], "source_group": d["source_group"],
            "source_entity_id": d["source_entitiy_id"],  # sic (pylmcp typo)
            "source_service_id": d["source_service_id"], "obj": d["obj"]}


class ZmqTransport(object):
    """Replays messages through PUSH and captures through SUB."""

    def __init__(self, endpoint, capture):
        self.zmq, self.Object, self.Message = _import_live()
        self.endpoint = endpoint
        self.capture = capture
        self.ctx = self.zmq.Context()
        self.sub = self.push = None
        self.raw = []
        self._stop = False
        self._thread = None
        self._t0 = None

    def open(self):
        zmq = self.zmq
        self.sub = self.ctx.socket(zmq.SUB)
        self.sub.connect(self.endpoint["pub"])
        for prefix in self.capture:
            self.sub.setsockopt(zmq.SUBSCRIBE, prefix.encode("utf-8"))
        self.push = self.ctx.socket(zmq.PUSH)
        self.push.connect(self.endpoint["push"])
        self._t0 = time.time()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self):
        zmq = self.zmq
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        while not self._stop:
            if poller.poll(timeout=100):
                raw = self.sub.recv()
                self.raw.append(((time.time() - self._t0) * 1000.0, raw))

    def send(self, msg):
        self.push.send(encode(msg, self.Object, self.Message))

    def close(self):
        self._stop = True
        if self._thread:
            self._thread.join(timeout=2)
        for s in (self.sub, self.push):
            if s is not None:
                s.close(0)
        self.ctx.term()

    def captured(self):
        out = []
        for t, raw in self.raw:
            try:
                out.append(decode(raw, t, self.Message))
            except Exception as e:  # undecodable: keep as opaque record
                out.append({"t_ms": t, "address": "<undecodable>",
                            "descriptor": "<undecodable>", "obj": {"error": str(e),
                                                                    "hex": raw.hex()}})
        return out
