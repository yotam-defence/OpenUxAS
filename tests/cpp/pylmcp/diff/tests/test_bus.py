import socket
import time

import pytest

import conftest  # noqa: F401  (sets sys.path)
from pylmcp.diff.bus import Bus, ClientBus, HubBus

zmq = pytest.importorskip("zmq")


def _url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return "tcp://127.0.0.1:%d" % port


def _until(fn, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        r = fn()
        if r:
            return r
        time.sleep(0.02)
    return fn()


@pytest.fixture
def ctx():
    c = zmq.Context()
    yield c
    c.destroy(linger=0)


def test_base_bus_defaults():
    with pytest.raises(NotImplementedError):
        Bus().poll()
    assert Bus().subscribers_seen() == -1


def test_client_bus_poll_before_open():
    assert ClientBus("tcp://127.0.0.1:1", "tcp://127.0.0.1:2").poll() == []


def test_client_bus_inject_and_poll(ctx):
    pub_url, pull_url = _url(), _url()
    pub = ctx.socket(zmq.PUB)
    pub.bind(pub_url)
    pull = ctx.socket(zmq.PULL)
    pull.bind(pull_url)
    bus = ClientBus(pub_url, pull_url)
    bus.open()
    try:
        bus.inject(b"hello")
        assert _until(lambda: pull.poll(50)) and pull.recv() == b"hello"

        got = []

        def recv():
            pub.send(b"frame")
            got.extend(bus.poll())
            return got
        assert _until(recv)[0] == b"frame"
    finally:
        bus.close()


def test_hub_bus_relays_and_counts_subscribers(ctx):
    pub_url, pull_url = _url(), _url()
    hub = HubBus(pub_url, pull_url)
    assert hub.poll() == []
    hub.open()
    sub = ctx.socket(zmq.SUB)
    push = ctx.socket(zmq.PUSH)
    try:
        sub.connect(pub_url)
        sub.setsockopt(zmq.SUBSCRIBE, b"")
        assert _until(lambda: hub.subscribers_seen() >= 1)

        push.connect(pull_url)
        push.send(b"up")
        frames = _until(hub.poll)
        assert frames == [b"up"]
        assert _until(lambda: sub.poll(50)) and sub.recv() == b"up"

        hub.inject(b"down")
        assert _until(lambda: sub.poll(50)) and sub.recv() == b"down"
    finally:
        hub.close()
