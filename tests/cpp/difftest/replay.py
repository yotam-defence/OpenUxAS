"""Scenario execution against one running implementation.

``execute_steps`` implements the deterministic timeline and is independent of
ZeroMQ (the transport is injected) so it is unit-testable.  ``ZmqTransport``
is the real transport built on pylmcp; zmq/pylmcp are imported lazily.
"""
import threading
import time
from typing import Any, Callable, Dict, List, Tuple

from difftest.model import DelayStep, Scenario, SendStep, WindowStep


def sleep_until(deadline: float, clock: Callable[[], float],
                sleep: Callable[[float], None]) -> None:
    remaining = deadline - clock()
    if remaining > 0:
        sleep(remaining)


def execute_steps(scenario: Scenario, transport,
                  clock: Callable[[], float] = time.monotonic,
                  sleep: Callable[[float], None] = time.sleep,
                  time_scale: float = 1.0
                  ) -> Tuple[float, List[Tuple[str, float]]]:
    """Run the steps and return ``(start_time, [(window, end_time)])``.

    Determinism: every step has a *scheduled* offset on a timeline anchored at
    ``start_time`` (cumulative delays/window durations multiplied by
    ``time_scale``).  Steps wait until their scheduled time rather than
    sleeping a relative amount, so send latency never accumulates drift and
    both implementations observe the same schedule.  Window boundaries are the
    scheduled times, not the observed ones.
    """
    start = clock()
    offset = 0.0
    boundaries: List[Tuple[str, float]] = []
    for step in scenario.steps:
        if isinstance(step, DelayStep):
            offset += step.delay_ms / 1000.0 * time_scale
            sleep_until(start + offset, clock, sleep)
        elif isinstance(step, SendStep):
            sleep_until(start + offset, clock, sleep)
            transport.send(step, scenario.config.entity_id)
        elif isinstance(step, WindowStep):
            offset += step.duration_ms / 1000.0 * time_scale
            sleep_until(start + offset, clock, sleep)
            boundaries.append((step.name, start + offset))
        else:  # pragma: no cover - guarded by scenario validation
            raise TypeError("unknown step %r" % (step,))
    return start, boundaries


def message_to_record(msg, t: float) -> Dict[str, Any]:
    """Convert a decoded ``pylmcp.message.Message`` to a capture record."""
    return {"address": msg.address,
            "descriptor": msg.descriptor,
            "content_type": msg.content_type,
            "source_group": msg.source_group,
            "source_entity_id": msg.source_entity_id,
            "source_service_id": msg.source_service_id,
            "type": msg.obj.object_class.full_name,
            "fields": msg.obj.as_dict(),
            "t": t}


class ZmqTransport:
    """Publish/pull client of one uxas bridge (what pylmcp.Server does).

    SUB connects to the bridge's ``AddressPUB`` to capture everything it
    publishes, PUSH connects to ``AddressPULL`` to inject messages.
    """

    def __init__(self, pub_url: str, pull_url: str,
                 clock: Callable[[], float] = time.monotonic):
        import zmq
        self._zmq = zmq
        self.clock = clock
        self.ctx = zmq.Context()
        self.sub = self.ctx.socket(zmq.SUB)
        self.sub.setsockopt(zmq.LINGER, 0)
        self.sub.setsockopt(zmq.SUBSCRIBE, b"")
        self.sub.connect(pub_url)
        self.push = self.ctx.socket(zmq.PUSH)
        self.push.setsockopt(zmq.LINGER, 500)
        self.push.connect(pull_url)
        self._raw: List[Tuple[float, bytes]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._listen, daemon=True,
                                        name="difftest-listen")
        self._thread.start()

    def _listen(self) -> None:
        poller = self._zmq.Poller()
        poller.register(self.sub, self._zmq.POLLIN)
        while not self._stop.is_set():
            if poller.poll(timeout=50):
                raw = self.sub.recv()
                with self._lock:
                    self._raw.append((self.clock(), raw))

    def send(self, step: SendStep, default_entity_id: int) -> None:
        from pylmcp.message import Message
        from difftest.scenario import build_object
        obj = build_object(step.spec)
        eid = step.source_entity_id
        msg = Message(obj=obj,
                      source_entity_id=default_entity_id if eid is None
                      else eid,
                      source_service_id=step.source_service_id,
                      source_group=step.source_group)
        self.push.send(msg.pack())

    def records(self) -> List[Dict[str, Any]]:
        from pylmcp.message import Message
        with self._lock:
            raw = list(self._raw)
        out = []
        for t, data in raw:
            try:
                out.append(message_to_record(Message.unpack(data), t))
            except Exception as e:  # undecodable output is itself a finding
                out.append({"address": data.split(b"$", 1)[0].decode(
                                "utf-8", "replace"),
                            "descriptor": "", "content_type": "",
                            "source_group": "", "source_entity_id": 0,
                            "source_service_id": 0,
                            "type": "__undecodable__",
                            "fields": {"error": "%s: %s" %
                                       (type(e).__name__, e)},
                            "t": t})
        return out

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.sub.close(0)
        self.push.close(500)
        self.ctx.term()
