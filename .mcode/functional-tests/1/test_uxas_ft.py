import json, os, re, shutil, subprocess, sys, tempfile, time
import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
UXAS = os.path.join(REPO, "obj", "cpp", "uxas")
RUNDIFF = os.path.join(REPO, "tests", "cpp", "run-diff")
GOLDEN = os.path.join(REPO, "tests", "cpp", "pylmcp", "diff", "golden", "smoke_heartbeat.cpp.json")


def sh(args, timeout=60, **kw):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kw)


def diff(*a, timeout=90):
    return sh([sys.executable, RUNDIFF, *a, ], timeout=timeout)


# ---------------- uxas CLI ----------------
@pytest.mark.parametrize("flag", ["--version", "-version"])
def test_version(flag):
    r = sh([UXAS, flag])
    assert r.returncode == 0
    assert re.search(r"VERSION:\s*\d+\.\d+\.\d+", r.stdout)


@pytest.mark.parametrize("flag", ["--help", "-help", "-h"])
def test_help(flag):
    r = sh([UXAS, flag])
    assert r.returncode == 0
    assert "Usage" in r.stdout and "-cfgPath" in r.stdout and "-runUntil" in r.stdout


@pytest.mark.parametrize("args,msg", [(["-cfgPath"], "-cfgPath"), (["-runUntil"], "-runUntil")])
def test_missing_value_errors(args, msg):
    r = sh([UXAS, *args])
    assert r.returncode != 0
    assert "Missing value" in (r.stdout + r.stderr) and msg in (r.stdout + r.stderr)


def test_unknown_arg_errors():
    r = sh([UXAS, "-bogus"])
    assert r.returncode != 0
    assert "Unrecognized" in r.stdout + r.stderr


def test_nonexistent_cfg_fails():
    r = sh([UXAS, "-cfgPath", "/nonexistent/cfg.xml"])
    assert r.returncode != 0


# ---------------- running uxas over ZeroMQ ----------------
def test_config_run_publishes_lmcp_heartbeat():
    zmq = pytest.importorskip("zmq")
    cfg = diff("gen-config", "smoke_heartbeat", "cpp")
    assert cfg.returncode == 0
    d = tempfile.mkdtemp()
    path = os.path.join(d, "cfg.xml")
    open(path, "w").write(cfg.stdout)
    p = subprocess.Popen([UXAS, "-cfgPath", path, "-runUntil", "12"], cwd=d,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ctx = zmq.Context()
    s = ctx.socket(zmq.SUB)
    s.setsockopt(zmq.SUBSCRIBE, b"")
    s.connect("tcp://127.0.0.1:5560")
    frames = []
    end = time.time() + 10
    while time.time() < end and len(frames) < 3:
        if s.poll(500):
            frames.append(s.recv())
    s.close(); ctx.term()
    try:
        rc = p.wait(timeout=30)
    finally:
        if p.poll() is None:
            p.kill()
        shutil.rmtree(d, ignore_errors=True)
    assert len(frames) >= 3
    assert all(b"afrl.cmasi.KeyValuePair" in f and b"smoke-heartbeat" in f for f in frames)
    assert rc == 0


# ---------------- harness CLI ----------------
def test_gen_config_cpp():
    r = diff("gen-config", "smoke_heartbeat", "cpp")
    assert r.returncode == 0
    assert 'Type="HelloWorld"' in r.stdout and "LmcpObjectNetworkPublishPullBridge" in r.stdout


def test_gen_config_ada_excludes_cpp_only_service():
    r = diff("gen-config", "smoke_heartbeat", "ada")
    assert r.returncode == 0
    assert "HelloWorld" not in r.stdout


def test_gen_config_unknown_scenario():
    assert diff("gen-config", "nosuch", "cpp").returncode == 2


def test_show_golden():
    r = diff("show", GOLDEN)
    assert r.returncode == 0
    assert "afrl.cmasi.KeyValuePair" in r.stdout and "smoke-heartbeat" in r.stdout


def test_show_missing_file():
    assert diff("show", "/nope.json").returncode == 2


def test_run_unknown_scenario():
    assert diff("run", "nosuch").returncode == 2


def test_run_no_scenario():
    assert diff("run").returncode == 2


def test_run_smoke_matches_golden():
    r = diff("run", "smoke_heartbeat", "--uxas", UXAS)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MATCH" in r.stdout and "MISMATCH" not in r.stdout


def test_run_report_file():
    d = tempfile.mkdtemp()
    rep = os.path.join(d, "rep.json")
    r = diff("run", "smoke_heartbeat", "--uxas", UXAS, "--report", rep)
    assert r.returncode == 0
    data = json.load(open(rep))
    assert data and data[0]["scenario"] == "smoke_heartbeat"
    shutil.rmtree(d)


def test_run_missing_binary_is_infra_error():
    r = diff("run", "smoke_heartbeat", "--uxas", "/nonexistent/uxas")
    assert r.returncode == 3


def test_run_detects_mismatch_silent_binary():
    fake = tempfile.mktemp()
    open(fake, "w").write("#!/bin/sh\nsleep 8\n")
    os.chmod(fake, 0o755)
    try:
        r = diff("run", "smoke_heartbeat", "--uxas", fake)
    finally:
        os.unlink(fake)
    assert r.returncode == 1
    assert "MISMATCH" in r.stdout


def test_run_detects_mismatch_tampered_golden():
    d = tempfile.mkdtemp()
    g = json.load(open(GOLDEN))
    # change the payload string of all frames: smoke-heartbeat -> smoke-heartbeaX
    for f in g["frames"]:
        f["frame_hex"] = f["frame_hex"].replace(b"smoke-heartbeat".hex(), b"smoke-heartbeaX".hex())
    json.dump(g, open(os.path.join(d, "smoke_heartbeat.cpp.json"), "w"))
    r = diff("run", "smoke_heartbeat", "--uxas", UXAS, "--golden-dir", d, "--allow-stale-golden")
    shutil.rmtree(d)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "MISMATCH" in r.stdout


def test_record_cpp_golden_and_rerun():
    d = tempfile.mkdtemp()
    r = diff("run", "smoke_heartbeat", "--uxas", UXAS, "--record-cpp-golden", "--golden-dir", d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "recorded" in r.stdout
    out = os.path.join(d, "smoke_heartbeat.cpp.json")
    assert os.path.isfile(out)
    r2 = diff("run", "smoke_heartbeat", "--uxas", UXAS, "--golden-dir", d)
    shutil.rmtree(d)
    assert r2.returncode == 0, r2.stdout + r2.stderr


def test_record_subcommand_captures_live_bus():
    cfg = diff("gen-config", "smoke_heartbeat", "cpp").stdout
    d = tempfile.mkdtemp()
    path = os.path.join(d, "cfg.xml")
    open(path, "w").write(cfg)
    p = subprocess.Popen([UXAS, "-cfgPath", path, "-runUntil", "12"], cwd=d,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)
    out = os.path.join(d, "rec.jsonl")
    try:
        r = diff("record", out, "--duration", "3")
    finally:
        p.terminate(); p.wait(timeout=30)
    lines = [l for l in open(out) if not l.startswith("#")]
    shutil.rmtree(d)
    assert r.returncode == 0 and "recorded" in r.stdout
    assert len(lines) >= 2
    assert "frame_hex" in lines[0]
