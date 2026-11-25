"""Tests for codec.py and runner.py using fakes (no pylmcp/pyzmq/binaries)."""
import base64
import subprocess
import sys
from types import SimpleNamespace

import pytest

from diffharness import codec, runner
from diffharness.scenario import ReplayStep, parse_scenario


def minimal(**over):
    d = {"name": "x", "capture": {"subscribe": ["a"]}, "replay": []}
    d.update(over)
    return d


# ---- codec ----------------------------------------------------------------

def _raw_step(**kw):
    return ReplayStep(delay_ms=0, address="A", source_group="g",
                      raw_b64=base64.b64encode(b"PAYLOAD").decode(), **kw)


def test_encode_step_raw_frame():
    assert codec.encode_step(_raw_step(), 100) == b"A$lmcp|A|g|100|0$PAYLOAD"


def test_encode_step_raw_frame_explicit_ids():
    data = codec.encode_step(
        _raw_step(source_entity_id=7, source_service_id=3), 100)
    assert data == b"A$lmcp|A|g|7|3$PAYLOAD"


class FakeObject:
    def __init__(self, type_, **kwargs):
        self.type = type_
        self.kwargs = kwargs


class FakeMessage:
    last = None
    unpack_result = None

    def __init__(self, **kwargs):
        FakeMessage.last = kwargs

    def pack(self):
        return b"packed"

    @staticmethod
    def unpack(raw):
        if isinstance(FakeMessage.unpack_result, Exception):
            raise FakeMessage.unpack_result
        return FakeMessage.unpack_result


@pytest.fixture
def fake_pylmcp(monkeypatch):
    monkeypatch.setattr(codec, "_pylmcp", lambda: (FakeObject, FakeMessage))
    FakeMessage.last = None
    FakeMessage.unpack_result = None


def test_encode_step_structured_uses_pylmcp(fake_pylmcp):
    step = ReplayStep(
        delay_ms=0, type="T", address="addr", source_group="grp",
        fields={"a": 1,
                "nested": {"$type": "N", "x": 2},
                "lst": [{"$type": "N", "x": 3}, 4]})
    assert codec.encode_step(step, 5) == b"packed"
    kw = FakeMessage.last
    assert (kw["source_entity_id"], kw["source_service_id"],
            kw["source_group"], kw["address"]) == (5, 0, "grp", "addr")
    obj = kw["obj"]
    assert obj.type == "T" and obj.kwargs["a"] == 1
    assert isinstance(obj.kwargs["nested"], FakeObject)
    assert obj.kwargs["nested"].kwargs == {"x": 2}
    assert isinstance(obj.kwargs["lst"][0], FakeObject)
    assert obj.kwargs["lst"][1] == 4


def _fake_obj(name, **data):
    return SimpleNamespace(object_class=SimpleNamespace(full_name=name),
                           data=data)


def test_obj_to_plain():
    obj = _fake_obj("A", n=1, b=b"\x00\x01", kids=[_fake_obj("B", v="s")],
                    tup=(1, 2))
    assert codec.obj_to_plain(obj) == {
        "$type": "A", "n": 1, "b": base64.b64encode(b"\x00\x01").decode(),
        "kids": [{"$type": "B", "v": "s"}], "tup": [1, 2]}


def test_decode_wire_ok(fake_pylmcp):
    FakeMessage.unpack_result = SimpleNamespace(
        address="a", descriptor="d", content_type="c", source_group="g",
        source_entity_id=1, source_service_id=2, obj=_fake_obj("T", k="v"))
    rec = codec.decode_wire(b"raw", t_ms=42)
    assert rec == {"t_ms": 42, "address": "a", "descriptor": "d",
                   "content_type": "c", "source_group": "g",
                   "source_entity_id": 1, "source_service_id": 2,
                   "obj": {"$type": "T", "k": "v"}}


def test_decode_wire_undecodable(fake_pylmcp):
    FakeMessage.unpack_result = ValueError("bad")
    raw = b"addr$garbage"
    rec = codec.decode_wire(raw)
    assert rec["address"] == "addr"
    assert rec["obj"]["$type"] == codec.UNDECODABLE
    assert rec["obj"]["error"] == "ValueError"
    assert base64.b64decode(rec["obj"]["raw_b64"]) == raw


def test_pylmcp_missing_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "pylmcp", None)
    with pytest.raises(codec.MissingDependency):
        codec._pylmcp()


# ---- runner ---------------------------------------------------------------

def test_connect_addr():
    assert runner._connect_addr("tcp://*:5560") == "tcp://127.0.0.1:5560"
    assert runner._connect_addr("tcp://10.0.0.1:5560") == "tcp://10.0.0.1:5560"


class FakeProc:
    def __init__(self, exited=False, waits=()):
        self.exited = exited
        self.waits = list(waits)  # True = raise TimeoutExpired
        self.calls = []

    def poll(self):
        return 0 if self.exited else None

    def send_signal(self, sig):
        self.calls.append("sigint")

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")

    def wait(self, timeout=None):
        self.calls.append("wait")
        if self.waits and self.waits.pop(0):
            raise subprocess.TimeoutExpired("p", timeout)


def test_stop_process_already_exited():
    p = FakeProc(exited=True)
    runner.stop_process(p, grace_s=0.01)
    assert p.calls == []


def test_stop_process_sigint_suffices():
    p = FakeProc(waits=[False])
    runner.stop_process(p, grace_s=0.01)
    assert p.calls == ["sigint", "wait"]


def test_stop_process_terminates():
    p = FakeProc(waits=[True, False])
    runner.stop_process(p, grace_s=0.01)
    assert p.calls == ["sigint", "wait", "terminate", "wait"]


def test_stop_process_kills():
    p = FakeProc(waits=[True, True, False])
    runner.stop_process(p, grace_s=0.01)
    assert p.calls == ["sigint", "wait", "terminate", "wait", "kill", "wait"]


class FakePoller:
    def __init__(self, ready):
        self.ready = list(ready)

    def poll(self, timeout=0):
        return self.ready.pop(0) if self.ready else []


class FakeSub:
    def recv(self):
        return b"msg"


@pytest.fixture
def fake_decode(monkeypatch):
    monkeypatch.setattr(runner.codec, "decode_wire",
                        lambda raw, t_ms=0: {"t_ms": t_ms, "raw": raw})


def test_drain_collects_records(fake_decode):
    import time
    records = []
    runner._drain(FakePoller([True]), FakeSub(), time.monotonic() + 0.1,
                  records, FakeProc(), time.monotonic())
    assert len(records) == 1 and records[0]["raw"] == b"msg"
    assert isinstance(records[0]["t_ms"], int)


def test_drain_drops_when_records_none(fake_decode):
    import time
    assert runner._drain(FakePoller([True]), FakeSub(),
                         time.monotonic() + 0.1, None, FakeProc(), 0.0,
                         return_on_msg=True) is True


def test_drain_returns_early_on_message(fake_decode):
    import time
    records = []
    assert runner._drain(FakePoller([True]), FakeSub(),
                         time.monotonic() + 5, records, FakeProc(),
                         time.monotonic(), return_on_msg=True) is True
    assert len(records) == 1


def test_drain_deadline_elapsed():
    import time
    assert runner._drain(FakePoller([]), FakeSub(), time.monotonic() - 1,
                         [], FakeProc(), 0.0) is False


def test_drain_returns_when_process_exited():
    import time
    assert runner._drain(FakePoller([]), FakeSub(), time.monotonic() + 5,
                         [], FakeProc(exited=True), 0.0) is False


def test_run_implementation_missing_binary(monkeypatch):
    monkeypatch.setattr(runner, "_zmq", lambda: object())
    sc = parse_scenario(minimal())
    with pytest.raises(runner.RunError):
        runner.run_implementation(sc, "cpp", "/nonexistent/uxas")


def test_run_implementation_ada_requires_hub(monkeypatch):
    monkeypatch.setattr(runner, "_zmq", lambda: object())
    sc = parse_scenario(minimal())
    with pytest.raises(runner.RunError):
        runner.run_implementation(sc, "ada", sys.executable, hub_binary=None)
