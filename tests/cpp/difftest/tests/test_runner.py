"""Runner/golden/config/timeline tests using fake backends (no binaries)."""
import json
import os

import pytest

from difftest import ADA, CPP
from difftest.cli import main
from difftest.config import render_config
from difftest.golden import GoldenError, read_golden, write_golden
from difftest.normalise import NormaliserConfig
from difftest.replay import execute_steps
from difftest.runner import Options, ScenarioResult, run_scenario
from difftest.scenario import parse_scenario

SC = {
    "name": "fake",
    "config": {"services": [
        {"type": {"ada": "AdaOnlyName", "cpp": "CppName"}},
        {"type": "AdaOnly", "impls": ["ada"]}]},
    "steps": [
        {"send": {"type": "KeyValuePair", "fields": {"Key": "k"}}},
        {"expect_window": {"name": "w1", "duration_ms": 100,
                           "min_messages": 1}},
        {"delay_ms": 50},
        {"expect_window": {"name": "w2", "duration_ms": 100}},
    ],
}


def rec(fields, typ="afrl.cmasi.KeyValuePair", t=0.0, svc=1):
    return {"address": typ, "descriptor": typ, "content_type": "lmcp",
            "source_group": "", "source_entity_id": 100,
            "source_service_id": svc, "type": typ, "fields": fields, "t": t}


class FakeBackend:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def capture(self, impl, scenario, binary, workdir, time_scale,
                startup_settle_ms=None):
        self.calls.append(impl)
        out = self.outputs[impl]
        if isinstance(out, Exception):
            raise out
        return out


def same(impl_value="1"):
    return {"w1": [rec({"Key": "k", "Value": impl_value, "Time": 1})],
            "w2": [], "__trailing__": []}


def opts(tmp_path, **kw):
    # existing executables so find_binary succeeds
    exe = tmp_path / "fakebin"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return Options(ada_bin=str(exe), cpp_bin=str(exe),
                   golden_dir=str(tmp_path / "goldens"),
                   workdir=str(tmp_path / "work"), **kw)


def test_live_pass_and_ignores_timestamps(tmp_path):
    sc = parse_scenario(SC)
    a = same()
    c = same()
    c["w1"][0]["fields"]["Time"] = 99999
    c["w1"][0]["source_service_id"] = 77
    r = run_scenario(sc, opts(tmp_path, mode="live"),
                     FakeBackend({ADA: a, CPP: c}))
    assert r.status == ScenarioResult.PASS, [str(d) for d in r.diffs]
    assert r.counts["w1"] == {ADA: 1, CPP: 1}


def test_live_mismatch(tmp_path):
    sc = parse_scenario(SC)
    r = run_scenario(sc, opts(tmp_path, mode="live"),
                     FakeBackend({ADA: same("1"), CPP: same("2")}))
    assert r.status == ScenarioResult.FAIL
    assert any(d.path == "fields.Value" for d in r.diffs)


def test_min_messages_bound(tmp_path):
    sc = parse_scenario(SC)
    empty = {"w1": [], "w2": [], "__trailing__": []}
    r = run_scenario(sc, opts(tmp_path, mode="live"),
                     FakeBackend({ADA: empty, CPP: empty}))
    assert r.status == ScenarioResult.FAIL
    assert any("at least 1" in str(d) for d in r.diffs)


def test_trailing_not_compared_but_noted(tmp_path):
    sc = parse_scenario(SC)
    c = same()
    c["__trailing__"] = [rec({"Key": "late"})]
    r = run_scenario(sc, opts(tmp_path, mode="live"),
                     FakeBackend({ADA: same(), CPP: c}))
    assert r.status == ScenarioResult.PASS
    assert any("after the last window" in n for n in r.notes)


def test_golden_roundtrip_and_stale(tmp_path):
    sc = parse_scenario(SC)
    o = opts(tmp_path, mode="record-golden")
    r = run_scenario(sc, o, FakeBackend({ADA: same(), CPP: None}))
    assert r.status == ScenarioResult.PASS and os.path.isfile(r.golden_path)
    doc = json.load(open(r.golden_path))
    assert "__trailing__" not in doc["windows"]
    assert "Time" not in json.dumps(doc["windows"])   # normalised

    # golden mode compares C++ only and never starts Ada
    be = FakeBackend({ADA: RuntimeError("must not run"), CPP: same()})
    r = run_scenario(sc, opts(tmp_path, mode="golden"), be)
    assert r.status == ScenarioResult.PASS and be.calls == [CPP]
    r = run_scenario(sc, opts(tmp_path, mode="golden"),
                     FakeBackend({CPP: same("other")}))
    assert r.status == ScenarioResult.FAIL

    # stale golden: scenario changed
    changed = dict(SC, description="changed")
    r = run_scenario(parse_scenario(changed), opts(tmp_path, mode="golden"),
                     FakeBackend({CPP: same()}))
    assert r.status == ScenarioResult.ERROR and "stale" in r.error
    r = run_scenario(parse_scenario(changed),
                     opts(tmp_path, mode="golden", allow_stale=True),
                     FakeBackend({CPP: same()}))
    assert r.status == ScenarioResult.PASS


def test_missing_golden_is_error(tmp_path):
    sc = parse_scenario(SC)
    r = run_scenario(sc, opts(tmp_path, mode="golden"),
                     FakeBackend({CPP: same()}))
    assert r.status == ScenarioResult.ERROR and "no golden" in r.error


def test_auto_mode_falls_back_to_golden(tmp_path):
    sc = parse_scenario(SC)
    o = opts(tmp_path, mode="record-golden")
    run_scenario(sc, o, FakeBackend({ADA: same()}))
    # Ada binary unavailable: auto -> golden
    o2 = opts(tmp_path, mode="auto")
    o2.ada_bin = None
    import difftest.runner as rn
    orig = rn.find_binary
    rn.find_binary = lambda impl, explicit=None: (
        None if impl == ADA else orig(impl, explicit))
    try:
        r = run_scenario(sc, o2, FakeBackend({CPP: same()}))
    finally:
        rn.find_binary = orig
    assert r.mode == "golden" and r.status == ScenarioResult.PASS


def test_infra_error_reported(tmp_path):
    sc = parse_scenario(SC)
    from difftest.procs import InfraError
    r = run_scenario(sc, opts(tmp_path, mode="live"),
                     FakeBackend({ADA: InfraError("ada died"), CPP: same()}))
    assert r.status == ScenarioResult.ERROR and "ada died" in r.error


def test_bad_explicit_binary_is_error(tmp_path):
    sc = parse_scenario(SC)
    o = opts(tmp_path, mode="live")
    o.cpp_bin = str(tmp_path / "nope")
    r = run_scenario(sc, o, FakeBackend({ADA: same(), CPP: same()}))
    assert r.status == ScenarioResult.ERROR


def test_golden_read_write_direct(tmp_path):
    sc = parse_scenario(SC)
    cfg = NormaliserConfig()
    write_golden(sc, cfg, {"w1": []}, str(tmp_path))
    assert read_golden(sc, cfg, str(tmp_path)) == {"w1": []}
    with pytest.raises(GoldenError):
        read_golden(sc, NormaliserConfig(float_digits=3), str(tmp_path))


def test_execute_steps_timeline_is_deterministic():
    sc = parse_scenario(SC)
    now = [100.0]
    sent = []

    class T:
        def send(self, step, eid):
            sent.append((now[0], eid))

    def sleep(d):
        now[0] += d

    # Sending takes time in the real world; schedule must not drift.
    start, bounds = execute_steps(sc, T(), clock=lambda: now[0], sleep=sleep)
    assert start == 100.0
    assert bounds == [("w1", pytest.approx(100.1)),
                      ("w2", pytest.approx(100.25))]
    assert sent == [(100.0, 100)]
    now[0] = 0.0
    _, b2 = execute_steps(sc, T(), clock=lambda: now[0], sleep=sleep,
                          time_scale=2.0)
    assert b2 == [("w1", pytest.approx(0.2)), ("w2", pytest.approx(0.5))]


def test_config_rendering_is_equivalent_except_declared():
    sc = parse_scenario(SC)
    ada = render_config(ADA, sc, "tcp://127.0.0.1:1", "tcp://127.0.0.1:2")
    cpp = render_config(CPP, sc, "tcp://127.0.0.1:1", "tcp://127.0.0.1:2")
    import xml.etree.ElementTree as ET
    ea, ec = ET.fromstring(ada.split("?>", 1)[1]), \
        ET.fromstring(cpp.split("?>", 1)[1])
    assert ea.attrib == ec.attrib == {"FormatVersion": "1.0",
                                      "EntityID": "100",
                                      "EntityType": "Aircraft"}
    ba, bc = ea.find("Bridge"), ec.find("Bridge")
    assert ET.tostring(ba) == ET.tostring(bc)
    assert ba.attrib["AddressPUB"] == "tcp://127.0.0.1:1"
    assert len(ba.findall("SubscribeToMessage")) == 52
    assert [s.attrib["Type"] for s in ea.findall("Service")] == \
        ["AdaOnlyName", "AdaOnly"]
    assert [s.attrib["Type"] for s in ec.findall("Service")] == ["CppName"]


def test_cli_exit_codes(tmp_path, capsys):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(SC))
    # no binaries and no golden -> infrastructure error (2)
    assert main([str(p), "--ada-bin", str(tmp_path / "x"),
                 "--golden-dir", str(tmp_path)]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert main([str(bad)]) == 2
    assert main(["--list-comparators"]) == 0
    assert "float_tolerance" in capsys.readouterr().out
