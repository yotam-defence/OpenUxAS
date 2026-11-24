import json, os, subprocess, sys, tempfile, time, copy
import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
UXAS = os.path.join(REPO, "obj", "cpp", "uxas")
DIFF = os.path.join(REPO, "tests", "diff")
GOLDEN = os.path.join(DIFF, "golden", "smoke_heartbeat.json")
DEPS = os.environ.get("DEPS_PREFIX", "/l2l/workspace/.uxas_deps")
PY = os.path.join(DEPS, "venv", "bin", "python")
ENV = dict(os.environ, LD_LIBRARY_PATH=DEPS + "/lib:" + os.environ.get("LD_LIBRARY_PATH", ""))


def sh(cmd, cwd=REPO, timeout=120, env=ENV):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def diffcli(*args, **kw):
    return sh([PY, "-m", "uxas_diff", *args], cwd=DIFF, **kw)


@pytest.fixture(scope="session", autouse=True)
def built():
    assert os.access(UXAS, os.X_OK), "uxas not built"


def test_version_long_exits_zero():
    r = sh([UXAS, "--version"])
    assert r.returncode == 0
    assert "VERSION" in r.stdout


def test_version_legacy_single_dash_prints_banner():
    # Legacy -version keeps its pre-existing behaviour: print the banner and
    # continue startup (so it can be combined with -cfgPath).
    r = sh([UXAS, "-version"], cwd="/tmp")
    assert "VERSION" in r.stdout


def test_help():
    r = sh([UXAS, "--help"])
    assert r.returncode == 0
    assert "Usage" in r.stdout + r.stderr


def test_missing_cfg_nonzero():
    r = sh([UXAS], cwd="/tmp")
    assert r.returncode != 0


def test_run_helloworld_config():
    cfg = os.path.join(REPO, "examples", "01_HelloWorld", "cfg_HelloWorld.xml")
    r = sh([UXAS, "-cfgPath", cfg, "-runUntil", "4"], cwd=os.path.join(REPO, "examples", "01_HelloWorld"), timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_smoke_golden_match():
    r = diffcli("run", "smoke_heartbeat", "--golden", "--uxas-bin", UXAS)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MATCH" in r.stdout and "4 msgs" in r.stdout


def test_canon():
    r = diffcli("canon", GOLDEN)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    types = {m["type"] for m in data}
    assert "afrl.cmasi.AirVehicleConfiguration" in types
    assert len(data) == 4


def test_diff_identical():
    r = diffcli("diff", GOLDEN, GOLDEN)
    assert r.returncode == 0 and "MATCH" in r.stdout


def test_diff_mismatch_exit1():
    g = json.load(open(GOLDEN))
    g["messages"][0]["obj"]["Label"] = "MUTATED"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(g, f)
    try:
        r = diffcli("diff", GOLDEN, f.name)
    finally:
        os.unlink(f.name)
    assert r.returncode == 1, r.stdout + r.stderr


def test_missing_binary_exit2():
    r = diffcli("run", "smoke_heartbeat", "--golden", "--uxas-bin", "/nonexistent/uxas")
    assert r.returncode == 2, r.stdout + r.stderr


def test_missing_scenario_exit2():
    r = diffcli("run", "no_such_scenario", "--golden", "--uxas-bin", UXAS)
    assert r.returncode == 2


def test_missing_golden_exit2(tmp_path):
    import shutil
    sc = tmp_path / "nogolden_scn"
    shutil.copytree(os.path.join(DIFF, "scenarios", "smoke_heartbeat"), sc)
    j = json.load(open(sc / "scenario.json"))
    j["name"] = "ft_nogolden_zzz"
    json.dump(j, open(sc / "scenario.json", "w"))
    r = diffcli("run", str(sc), "--golden", "--uxas-bin", UXAS)
    assert r.returncode == 2, r.stdout + r.stderr
