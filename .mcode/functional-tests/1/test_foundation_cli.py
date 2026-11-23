import json, os, subprocess, time, signal, copy
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
UXAS = os.path.join(ROOT, "obj", "cpp", "uxas")
RUNDIFF = os.path.join(ROOT, "tests", "cpp", "run-diff")
SMOKE = os.path.join(ROOT, "tests", "cpp", "run-smoke")
SCEN = os.path.join(ROOT, "tests", "cpp", "difftool", "scenarios", "heartbeat_smoke.json")
GOLDEN = os.path.join(ROOT, "tests", "cpp", "difftool", "golden", "heartbeat_smoke.ada.golden.json")


def sh(args, **kw):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True, timeout=120, **kw)


def rd(*a):
    return sh([RUNDIFF] + list(a))


@pytest.fixture(scope="module")
def caps(tmp_path_factory):
    d = tmp_path_factory.mktemp("caps")
    msgs = json.load(open(GOLDEN))["messages"]

    def w(name, m):
        p = str(d / name)
        json.dump({"format": 1, "messages": m}, open(p, "w"))
        return p
    out = {"base": w("base.json", msgs)}
    out["shift"] = w("shift.json", [dict(x, t_ms=x["t_ms"] + 5000) for x in msgs])
    c = copy.deepcopy(msgs); c[2]["obj"]["Value"] = "DIFF"; out["diff"] = w("diff.json", c)
    c = copy.deepcopy(msgs); c[1], c[2] = c[2], c[1]
    c[1]["t_ms"], c[2]["t_ms"] = msgs[1]["t_ms"], msgs[2]["t_ms"]
    out["swap"] = w("swap.json", c)
    a = copy.deepcopy(msgs); b = copy.deepcopy(msgs)
    for i, x in enumerate(a): x["obj"]["RequestID"] = 1000 + i
    for i, x in enumerate(b): x["obj"]["RequestID"] = 5 + i
    out["ids_a"] = w("ids_a.json", a); out["ids_b"] = w("ids_b.json", b)
    out["short"] = w("short.json", msgs[:3])
    return out


def test_uxas_version_banner():
    r = sh([UXAS, "-version"])
    assert r.returncode == 100
    assert "VERSION: 3.2.0" in r.stdout and "CMASI" in r.stdout


def test_uxas_unrecognized_arg_help():
    r = sh([UXAS, "-help"])
    assert "Unrecognized argument -help" in r.stdout


def test_uxas_hello_world_runs():
    cwd = os.path.join(ROOT, "examples", "01_HelloWorld")
    p = subprocess.Popen([UXAS, "-cfgPath", "cfg_HelloWorld.xml"], cwd=cwd,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    try:
        time.sleep(4)
        assert p.poll() is None, "uxas exited early: %s" % p.stdout.read()
    finally:
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()


def test_selftest():
    r = rd("--selftest")
    assert r.returncode == 0, r.stdout


def test_smoke_match():
    r = sh(["bash", SMOKE, os.path.join(ROOT, "obj", "cpp")])
    assert r.returncode == 0 and "RESULT: MATCH" in r.stdout, r.stdout


def test_compare_identical(caps):
    r = rd("--scenario", SCEN, "--compare-files", caps["base"], caps["base"])
    assert r.returncode == 0 and "RESULT: MATCH" in r.stdout


def test_canonical_timestamps_ignored(caps):
    r = rd("--scenario", SCEN, "--compare-files", caps["base"], caps["shift"])
    assert r.returncode == 0, r.stdout


def test_canonical_ordering_within_window(caps):
    r = rd("--scenario", SCEN, "--compare-files", caps["base"], caps["swap"])
    assert r.returncode == 0, r.stdout


def test_canonical_ids_renumbered(caps):
    r = rd("--scenario", SCEN, "--compare-files", caps["ids_a"], caps["ids_b"])
    assert r.returncode == 0, r.stdout


def test_compare_value_difference(caps):
    r = rd("--scenario", SCEN, "--compare-files", caps["base"], caps["diff"])
    assert r.returncode == 1 and "body.Value" in r.stdout and "DIFF" in r.stdout


def test_compare_missing_message(caps):
    r = rd("--scenario", SCEN, "--compare-files", caps["base"], caps["short"])
    assert r.returncode == 1 and "missing_in_cpp" in r.stdout


def test_exit2_no_scenario(caps):
    assert rd("--compare-files", caps["base"], caps["base"]).returncode == 2


def test_exit2_bad_scenario(caps):
    assert rd("--scenario", "/nonexistent.json", "--compare-files", caps["base"], caps["base"]).returncode == 2


def test_exit2_unknown_option():
    assert rd("--bogus").returncode == 2


def test_exit3_missing_capture(caps):
    assert rd("--scenario", SCEN, "--compare-files", caps["base"], "/nonexistent.json").returncode == 3


def test_exit4_golden_missing(tmp_path):
    r = rd("--scenario", SCEN, "--cpp-bin", UXAS, "--golden", str(tmp_path))
    assert r.returncode == 4 and "no golden file" in r.stdout
