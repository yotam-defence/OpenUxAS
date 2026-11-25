import json, os, shutil, socket, subprocess, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CPP = os.path.join(ROOT, "tests", "cpp")
BIN = os.path.join(ROOT, "obj", "cpp", "uxas")
SCEN = os.path.join(CPP, "difftest", "scenarios", "smoke.json")
PY = os.path.join(ROOT, ".vpython", "bin", "python")
PY = PY if os.path.exists(PY) else sys.executable


def difftest(*args):
    return subprocess.run([PY, "-m", "difftest", *args], cwd=CPP, capture_output=True, text=True, timeout=120)


def test_ports_listening():
    for p in (5561, 5562):
        with socket.create_connection(("127.0.0.1", p), timeout=3):
            pass


def test_self_consistency_live():
    r = difftest("--mode", "live", "--ada-bin", BIN, "--cpp-bin", BIN, SCEN)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 passed" in r.stdout


def test_golden_record_then_compare_and_mismatch():
    d = tempfile.mkdtemp()
    try:
        r = difftest("--mode", "record-golden", "--ada-bin", BIN, "--golden-dir", d, SCEN)
        assert r.returncode == 0, r.stdout + r.stderr
        r = difftest("--mode", "golden", "--cpp-bin", BIN, "--golden-dir", d, SCEN)
        assert r.returncode == 0, r.stdout + r.stderr
        g = os.path.join(d, "smoke.json")
        data = json.load(open(g))
        w = data["windows"]["after-ticks"]
        w.pop()
        json.dump(data, open(g, "w"))
        r = difftest("--mode", "golden", "--cpp-bin", BIN, "--golden-dir", d, SCEN)
        assert r.returncode == 1, r.stdout + r.stderr
    finally:
        shutil.rmtree(d)


def test_missing_scenario_error():
    r = difftest("--mode", "live", "--cpp-bin", BIN, "/nonexistent.json")
    assert r.returncode == 2


def test_uxas_help_flags():
    for flag in ("-help", "--help"):
        r = subprocess.run([BIN, flag], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, flag + ": " + r.stdout + r.stderr
        assert "Usage:" in r.stdout, flag
        assert "-cfgPath" in r.stdout and "-runUntil" in r.stdout, flag


def test_uxas_version_flags():
    for flag in ("-version", "--version"):
        r = subprocess.run([BIN, flag], capture_output=True, text=True, timeout=30)
        assert "VERSION:" in r.stdout and "CMASI:" in r.stdout and "IMPACT:" in r.stdout, flag
