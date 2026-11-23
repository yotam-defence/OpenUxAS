import json, os, subprocess, sys, tempfile
import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
UXAS = os.path.join(REPO, "obj", "cpp", "uxas")
CPP = os.path.join(REPO, "tests", "cpp")
SCEN = "difftest/scenarios/smoke_heartbeat.json"
ENV = dict(os.environ)
deps = os.environ.get("DEPS_PREFIX", "/l2l/workspace/.deps")
ENV["LD_LIBRARY_PATH"] = deps + "/lib:" + ENV.get("LD_LIBRARY_PATH", "")
ENV["PYTHONPATH"] = CPP


def sh(cmd, cwd=REPO, timeout=120):
    return subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=timeout)


def dt(*args):
    return sh([sys.executable, "-m", "difftest", *args], cwd=CPP)


@pytest.mark.parametrize("flag", ["-version", "-help", "--help", "-h"])
def test_uxas_info_flags(flag):
    r = sh([UXAS, flag])
    assert r.returncode == 0
    assert ("VERSION" in r.stdout) if "version" in flag else ("Usage" in r.stdout)


@pytest.mark.parametrize("flag", ["-cfgPath", "-runUntil"])
def test_uxas_missing_value_is_error(flag):
    r = sh([UXAS, flag])
    assert r.returncode != 0
    assert "Missing value" in r.stdout + r.stderr


def test_list_comparators():
    r = dt("list-comparators")
    assert r.returncode == 0
    for c in ("exact", "numeric", "count", "cpp_superset", "ignore"):
        assert c in r.stdout


def test_smoke_live_match():
    r = dt("run", SCEN, "--ada-golden", "--cpp-bin", UXAS)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MATCH" in r.stdout


def test_make_diff_smoke():
    r = sh(["make", "diff-smoke", "PYTHON=" + sys.executable])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MATCH" in r.stdout


def test_differing_capture_yields_diff():
    with tempfile.TemporaryDirectory() as d:
        g = os.path.join(d, "smoke_heartbeat.ada.json")
        json.dump({"version": 1, "scenario": "smoke_heartbeat", "binary": "ada",
                   "messages": [{"t_ms": 1.0, "address": "x", "descriptor": "afrl.cmasi.AirVehicleState",
                                 "content": {"ID": 1}}]}, open(g, "w"))
        r = dt("run", SCEN, "--ada-golden", "--cpp-bin", UXAS, "--golden-dir", d)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "DIFF" in r.stdout.upper()


def test_missing_golden_is_error():
    with tempfile.TemporaryDirectory() as d:
        r = dt("run", SCEN, "--ada-golden", "--cpp-bin", UXAS, "--golden-dir", d)
        assert r.returncode == 2


def test_compare_offline_match_and_diff():
    with tempfile.TemporaryDirectory() as d:
        a, b, c = (os.path.join(d, n) for n in ("a.json", "b.json", "c.json"))
        msg = {"t_ms": 1.0, "address": "x", "descriptor": "afrl.cmasi.AirVehicleState",
               "content": {"Key": "k", "Value": "v"}}
        for p, m in ((a, [msg]), (b, [msg]), (c, [])):
            json.dump({"version": 1, "scenario": "s", "binary": "x", "messages": m}, open(p, "w"))
        assert dt("compare", a, b, "--scenario", os.path.join(CPP, SCEN)).returncode == 0
        assert dt("compare", a, c, "--scenario", os.path.join(CPP, SCEN)).returncode == 1


def test_make_test_gtest():
    r = sh(["make", "test", "-j8"], timeout=600)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
