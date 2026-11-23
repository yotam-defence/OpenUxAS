import json, os, subprocess, sys, shutil
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
UXAS = os.path.join(ROOT, os.environ.get("UXAS_BIN", "obj/cpp/uxas"))
DIFF = os.path.join(ROOT, "tests/cpp/differential")
RUN = os.path.join(DIFF, "run_differential.py")
SCEN = os.path.join(DIFF, "scenarios/heartbeat.json")


def sh(args, timeout=120):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def diff(*extra, scenario=SCEN, bin=UXAS):
    return sh([sys.executable, "-E", RUN, scenario, "--cpp-bin", bin, *extra])


@pytest.fixture(scope="module")
def golden(tmp_path_factory):
    p = str(tmp_path_factory.mktemp("g") / "g.json")
    r = diff("--record-golden", p, "--golden-side", "cpp", "--record-only")
    assert r.returncode == 0, r.stdout + r.stderr
    return p


@pytest.mark.parametrize("flag", ["--version", "-version"])
def test_uxas_version(flag):
    r = sh([UXAS, flag])
    assert r.returncode == 0 and "VERSION" in r.stdout


@pytest.mark.parametrize("flag", ["--help", "-help"])
def test_uxas_help(flag):
    r = sh([UXAS, flag])
    assert r.returncode == 0 and (r.stdout + r.stderr).strip()


def test_cpp_only_heartbeat_replay(tmp_path):
    rep = str(tmp_path / "r.json")
    r = diff("--cpp-only", "--report", rep)
    assert r.returncode == 0, r.stdout + r.stderr
    d = json.load(open(rep))
    assert d["parity_checked"] is False
    assert d["report"]["cand_count"] > 0 and d["report"]["equal"] is True
    assert "parity not checked" in r.stdout + r.stderr


def test_golden_match(golden):
    r = diff("--golden", golden)
    assert r.returncode == 0 and "MATCH" in r.stdout


def test_golden_mismatch_detected(golden, tmp_path):
    d = json.load(open(golden))
    d["records"][0]["fields"]["Value"] = "tampered"
    p = str(tmp_path / "bad.json")
    json.dump(d, open(p, "w"))
    assert diff("--golden", p).returncode == 1


def test_missing_golden_exit4(tmp_path):
    assert diff("--golden", str(tmp_path / "nope.json")).returncode == 4


def test_corrupt_golden_exit4(tmp_path):
    p = tmp_path / "c.json"; p.write_text("{not json")
    assert diff("--golden", str(p)).returncode == 4


def test_missing_scenario_exit2(tmp_path):
    assert diff("--cpp-only", scenario=str(tmp_path / "x.json")).returncode == 2


def test_cpp_only_with_golden_usage_error(golden):
    assert diff("--cpp-only", "--golden", golden).returncode == 2


def test_missing_binary_exit3(tmp_path):
    assert diff("--cpp-only", bin=str(tmp_path / "nouxas")).returncode == 3


def test_crashing_binary_exit3(tmp_path):
    f = tmp_path / "fake"; f.write_text("#!/bin/sh\nexit 7\n"); f.chmod(0o755)
    assert diff("--cpp-only", bin=str(f)).returncode == 3


def test_list_comparators():
    r = sh([sys.executable, "-E", RUN, "--list-comparators"])
    assert r.returncode == 0 and "heartbeat" in r.stdout
