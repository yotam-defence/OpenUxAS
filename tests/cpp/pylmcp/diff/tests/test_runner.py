"""Runner/golden/CLI tests using stub fake processes and an in-memory bus."""
import os

import pytest

from helpers import kv_frame
from pylmcp.diff import cli
from pylmcp.diff.capture import (Capture, GoldenError, load_golden,
                                 save_golden)
from pylmcp.diff.runner import (RunContext, RunError, record_cpp_golden,
                                run_scenario, run_side)
from pylmcp.diff.scenario import load_scenario, parse_scenario
from pylmcp.diff.testing import FakeBus, FakeClock, FakeLauncher

SMOKE = os.path.join(os.path.dirname(__file__), "..", "scenarios",
                     "smoke_heartbeat.json")


def make_ctx(responders=None, echo_cpp=True, launcher=None, **kw):
    """responders: side -> callable(frame) -> [frames]"""
    clock = FakeClock()
    responders = responders or {}
    buses = {}

    def factory(side, sc):
        buses[side] = FakeBus(responders.get(side),
                              echo=(echo_cpp and side == "cpp"))
        return buses[side]

    ctx = RunContext(binaries={"ada": "/x/uxas_ada", "cpp": "/x/uxas"},
                     launcher=launcher or FakeLauncher(),
                     bus_factory=factory, sleep=clock.sleep, clock=clock,
                     **kw)
    ctx.buses = buses
    return ctx


def reply(frame):
    """A 'service' reacting to each heartbeat with a KeyValuePair."""
    return [kv_frame("ack", "x", entity=100, service=42)]


def test_smoke_scenario_matches_with_fakes():
    sc = load_scenario(SMOKE)
    ctx = make_ctx({"ada": reply, "cpp": reply})
    res = run_scenario(sc, ctx, ada="live", cpp="live")
    assert res.ok, res.format()
    # configs were handed to both binaries
    assert len(ctx.launcher.started) == 2
    assert ctx.launcher.started[0].argv[:2] == ["/x/uxas_ada", "-cfgPath"]
    assert all(p.stopped for p in ctx.launcher.started)
    assert all(b.closed for b in ctx.buses.values())
    # all 3 heartbeats injected on both sides
    assert len(ctx.buses["ada"].injected) == 3


def test_replay_is_deterministic_windows_and_echo_filtered():
    sc = load_scenario(SMOKE)
    sc.capture.window = "step"          # per-step windows for this check
    ctx = make_ctx({"cpp": reply, "ada": reply})
    cap = run_side("cpp", sc, ctx)
    # echo of the 3 injected frames dropped; 1 ack per step remains
    assert len(cap.frames) == 3
    assert [f.window for f in cap.frames] == [1, 2, 3]
    cap2 = run_side("cpp", sc, make_ctx({"cpp": reply}))
    assert [f.data for f in cap.frames] == [f.data for f in cap2.frames]


def test_echo_filter_none_keeps_echo():
    sc = parse_scenario({"format_version": 1, "name": "e",
                         "capture": {"echo_filter": "none"},
                         "replay": [{"frame_hex": kv_frame().hex()}]})
    cap = run_side("cpp", sc, make_ctx())
    assert len(cap.frames) == 1


def test_window_modes():
    base = {"format_version": 1, "name": "w",
            "replay": [{"frame_hex": kv_frame("a").hex()},
                       {"frame_hex": kv_frame("b").hex()}]}
    for mode in ("all", "fixed:100"):
        sc = parse_scenario(dict(base, capture={"window": mode,
                                                "echo_filter": "none"}))
        cap = run_side("cpp", sc, make_ctx())
        if mode == "all":
            assert {f.window for f in cap.frames} == {0}
        else:
            assert len({f.window for f in cap.frames}) >= 1


def test_mismatch_detected():
    sc = load_scenario(SMOKE)
    ctx = make_ctx({"ada": reply})       # only Ada reacts
    res = run_scenario(sc, ctx, ada="live", cpp="live")
    assert not res.ok
    assert {d.kind for d in res.differences} == {"missing", "count"}


def test_ids_and_order_noise_do_not_cause_mismatch():
    def mk(order_rev, svc):
        def r(frame):
            out = [kv_frame("a", "1", service=svc),
                   kv_frame("b", "2", service=svc)]
            return out[::-1] if order_rev else out
        return r
    sc = load_scenario(SMOKE)
    res = run_scenario(sc, make_ctx({"ada": mk(False, 1),
                                     "cpp": mk(True, 9)}),
                       ada="live", cpp="live")
    assert res.ok, res.format()


def test_process_dies_is_reported():
    sc = load_scenario(SMOKE)
    with pytest.raises(RunError) as e:
        run_side("cpp", sc, make_ctx(launcher=FakeLauncher(True)))
    assert "exited unexpectedly" in str(e.value) and "fake log" in str(e.value)


def test_missing_binary():
    sc = load_scenario(SMOKE)
    ctx = make_ctx()
    ctx.binaries["ada"] = None
    with pytest.raises(RunError):
        run_side("ada", sc, ctx)


def test_golden_roundtrip_and_use(tmp_path):
    sc = load_scenario(SMOKE)
    gd = str(tmp_path / "g")
    # 1. record golden for both sides from live (fake) runs
    ctx = make_ctx({"ada": reply, "cpp": reply})
    res = run_scenario(sc, ctx, ada="live", cpp="live", golden_dir=gd,
                       update_golden=True)
    assert res.ok
    assert sorted(os.listdir(gd)) == ["smoke_heartbeat.ada.json",
                                      "smoke_heartbeat.cpp.json"]
    # 2. now run with Ada from golden: Ada binary/launcher must not be used
    ctx2 = make_ctx({"cpp": reply})
    ctx2.binaries["ada"] = None
    res2 = run_scenario(sc, ctx2, ada="auto", cpp="live", golden_dir=gd)
    assert res2.ok and any("golden" in n for n in res2.notes)
    assert len(ctx2.launcher.started) == 1
    # 3. golden mismatch is a real diff
    ctx3 = make_ctx({})
    ctx3.binaries["ada"] = None
    assert not run_scenario(sc, ctx3, ada="golden", cpp="live",
                            golden_dir=gd).ok


def test_golden_missing_and_stale(tmp_path):
    sc = load_scenario(SMOKE)
    gd = str(tmp_path)
    with pytest.raises(GoldenError):
        load_golden(gd, sc.name, "ada")
    with pytest.raises(RunError):
        run_scenario(sc, make_ctx(), ada="golden", cpp="live", golden_dir=gd)
    cap = Capture("ada", sc.name, fingerprint="old")
    save_golden(gd, cap)
    with pytest.raises(GoldenError):
        load_golden(gd, sc.name, "ada", sc.capture_fingerprint("ada"))
    load_golden(gd, sc.name, "ada", sc.capture_fingerprint("ada"),
                allow_stale=True)
    # auto falls back to a live run on stale golden
    res = run_scenario(sc, make_ctx({"ada": reply, "cpp": reply}),
                       ada="auto", cpp="live", golden_dir=gd)
    assert res.ok and not res.notes
    (tmp_path / "smoke_heartbeat.ada.json").write_text("{bad")
    with pytest.raises(GoldenError):
        load_golden(gd, sc.name, "ada")


def test_min_messages_enforced():
    sc = parse_scenario({"format_version": 1, "name": "m",
                         "capture": {"min_messages": 1}})
    res = run_scenario(sc, make_ctx(), ada="live", cpp="live")
    assert not res.ok and res.differences[0].kind == "count"


def test_cli_gen_config_show_and_errors(capsys, tmp_path, monkeypatch):
    monkeypatch.delenv('UXAS_BIN', raising=False)
    monkeypatch.delenv('UXAS_ADA_BIN', raising=False)
    monkeypatch.setattr(cli.shutil, 'which', lambda n: None)
    assert cli.main(["gen-config", SMOKE, "cpp"]) == cli.EXIT_OK
    assert "AutomationRequestValidatorService" in capsys.readouterr().out
    assert cli.main(["run", "no_such_scenario"]) == cli.EXIT_USAGE
    assert cli.main(["gen-config", "nope", "ada"]) == cli.EXIT_USAGE
    # no binaries + no golden => infrastructure error (exit 3), no crash
    rc = cli.main(["run", "smoke_heartbeat", "--uxas", "", "--uxas-ada", "",
                   "--golden-dir", str(tmp_path)])
    assert rc == cli.EXIT_INFRA
    # show a golden produced by the fakes
    sc = load_scenario(SMOKE)
    cap = run_side("cpp", sc, make_ctx({"cpp": reply}))
    path = save_golden(str(tmp_path), cap)
    assert cli.main(["show", path]) == cli.EXIT_OK
    assert "afrl.cmasi.KeyValuePair" in capsys.readouterr().out


# ------------------------------------------------ non-vacuous smoke gate

COMMITTED_GOLDEN = os.path.join(os.path.dirname(__file__), "..", "golden")


def test_smoke_scenario_is_not_vacuous():
    sc = load_scenario(SMOKE)
    assert sc.capture.min_messages >= 1
    assert any(r.use == "distinct" for r in sc.comparators)
    # silence on both sides must now fail the gate
    res = run_scenario(sc, make_ctx(), ada="live", cpp="live")
    assert not res.ok and {d.kind for d in res.differences} == {"count"}


def test_committed_cpp_golden_is_labelled_and_fresh():
    sc = load_scenario(SMOKE)
    cap = load_golden(COMMITTED_GOLDEN, sc.name, "cpp",
                      sc.capture_fingerprint("cpp"))
    assert cap.meta["recorded_from"] == "cpp"
    assert cap.meta["reference_is_ada"] is False
    assert "--update-golden" in cap.meta["note"]
    assert len(cap.frames) >= sc.capture.min_messages
    # never fabricate Ada output: there must be no committed Ada golden
    assert not os.path.exists(os.path.join(COMMITTED_GOLDEN,
                                           "smoke_heartbeat.ada.json"))


def test_cpp_golden_regression_gate_when_ada_absent(tmp_path):
    sc = load_scenario(SMOKE)
    gd = str(tmp_path)
    record_cpp_golden(sc, make_ctx({"cpp": reply}), gd)
    assert os.listdir(gd) == ["smoke_heartbeat.cpp.json"]
    assert load_golden(gd, sc.name, "cpp").meta["reference_is_ada"] is False
    # Ada unavailable: live C++ is compared against the C++ golden
    ctx = make_ctx({"cpp": reply})
    ctx.binaries["ada"] = None
    res = run_scenario(sc, ctx, ada="auto", cpp="live", golden_dir=gd)
    assert res.ok and any("REGRESSION GATE" in n for n in res.notes)
    assert len(ctx.launcher.started) == 1
    # a C++ regression (different output) is detected
    ctx = make_ctx({"cpp": lambda f: [kv_frame("other", "y")]})
    ctx.binaries["ada"] = None
    assert not run_scenario(sc, ctx, ada="auto", cpp="live",
                            golden_dir=gd).ok
    # no golden at all: infrastructure error, not a silent pass
    ctx = make_ctx({"cpp": reply})
    ctx.binaries["ada"] = None
    with pytest.raises(RunError):
        run_scenario(sc, ctx, ada="auto", cpp="live",
                     golden_dir=str(tmp_path / "none"))


def test_record_cpp_golden_requires_min_messages(tmp_path):
    sc = load_scenario(SMOKE)
    with pytest.raises(RunError):
        record_cpp_golden(sc, make_ctx(), str(tmp_path))
