import time
from types import SimpleNamespace

import pytest

from difftest.procs import find_free_ports
from difftest.replay import message_to_record


def test_message_to_record_maps_fields():
    obj = SimpleNamespace(object_class=SimpleNamespace(full_name="afrl.cmasi.X"),
                          as_dict=lambda: {"a": 1})
    msg = SimpleNamespace(address="addr", descriptor="d", content_type="ct",
                          source_group="g", source_entity_id=7,
                          source_service_id=3, obj=obj)
    assert message_to_record(msg, 1.5) == {
        "address": "addr", "descriptor": "d", "content_type": "ct",
        "source_group": "g", "source_entity_id": 7, "source_service_id": 3,
        "type": "afrl.cmasi.X", "fields": {"a": 1}, "t": 1.5}


@pytest.fixture
def transport_env():
    zmq = pytest.importorskip("zmq")
    from difftest.replay import ZmqTransport
    pub_port, pull_port = find_free_ports(2)
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind("tcp://127.0.0.1:%d" % pub_port)
    pull = ctx.socket(zmq.PULL)
    pull.bind("tcp://127.0.0.1:%d" % pull_port)
    ticks = iter(range(1, 10 ** 6))
    t = ZmqTransport("tcp://127.0.0.1:%d" % pub_port,
                     "tcp://127.0.0.1:%d" % pull_port,
                     clock=lambda: float(next(ticks)))
    try:
        yield zmq, t, pub, pull
    finally:
        t.close()
        pub.close(0)
        pull.close(0)
        ctx.term()


def _publish_until_captured(t, pub, payload, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pub.send(payload)  # repeat: SUB may not be connected yet
        time.sleep(0.05)
        with t._lock:
            if t._raw:
                return
    raise AssertionError("transport never captured a published message")


def test_capture_uses_injected_clock(transport_env):
    _, t, pub, _ = transport_env
    _publish_until_captured(t, pub, b"addr$garbage")
    with t._lock:
        ts, raw = t._raw[0]
    assert raw == b"addr$garbage"
    assert ts == float(int(ts))  # produced by the fake integer clock


def test_undecodable_output_becomes_finding(transport_env):
    pytest.importorskip("pylmcp")
    _, t, pub, _ = transport_env
    _publish_until_captured(t, pub, b"addr$garbage")
    rec = t.records()[0]
    assert rec["type"] == "__undecodable__"
    assert rec["address"] == "addr"
    assert rec["fields"]["error"]


def test_close_stops_listener_thread():
    pytest.importorskip("zmq")
    from difftest.replay import ZmqTransport
    pub_port, pull_port = find_free_ports(2)
    t = ZmqTransport("tcp://127.0.0.1:%d" % pub_port,
                     "tcp://127.0.0.1:%d" % pull_port)
    assert t._thread.is_alive()
    t.close()
    assert not t._thread.is_alive()
