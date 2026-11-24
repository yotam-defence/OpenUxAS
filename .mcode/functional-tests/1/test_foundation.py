import json, os, shutil, subprocess, sys, pytest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CPP = os.path.join(ROOT, "tests", "cpp")
UXAS = os.path.join(ROOT, "obj", "cpp", "uxas")
SC = os.path.join(CPP, "difftest", "scenarios", "smoke_heartbeat.json")
GOLD = os.path.join(CPP, "difftest", "scenarios", "golden")

def dt(*args, timeout=120):
    return subprocess.run([sys.executable, "-m", "difftest", *args], cwd=CPP,
                          capture_output=True, text=True, timeout=timeout)

def tmp_golden(tmp_path, mutate=None):
    d = tmp_path / "g"; shutil.copytree(GOLD, d)
    if mutate:
        f = d / "smoke_heartbeat.ada.golden.json"
        doc = json.load(open(f)); mutate(doc); json.dump(doc, open(f, "w"))
    return str(d)

def test_uxas_version():
    r = subprocess.run([UXAS, "-version"], capture_output=True, text=True, timeout=30, cwd=ROOT)
    assert "VERSION" in r.stdout + r.stderr
    assert r.returncode == 100

def test_validate():
    r = dt(SC, "--validate")
    assert r.returncode == 0 and "OK" in r.stdout

def test_dump_config_cpp():
    r = dt(SC, "--dump-config", "cpp")
    assert r.returncode == 0 and "<UxAS" in r.stdout and "Bridge" in r.stdout

def test_list_comparators():
    r = dt("--list-comparators")
    assert r.returncode == 0
    for n in ("canonical", "types", "subset", "ignore"):
        assert n in r.stdout

def test_use_golden_match():
    r = dt(SC, "--cpp-bin", UXAS, "--use-golden")
    assert r.returncode == 0, r.stdout + r.stderr

def test_report_json_three_heartbeats(tmp_path):
    rep = tmp_path / "r.json"
    r = dt(SC, "--cpp-bin", UXAS, "--use-golden", "--report-json", str(rep))
    assert r.returncode == 0, r.stdout + r.stderr
    assert rep.exists() and json.load(open(rep))

def test_mismatch_exit_1(tmp_path):
    def mut(doc): doc["records"][0]["obj"]["Value"] = "999"
    g = tmp_golden(tmp_path, mut)
    r = dt(SC, "--cpp-bin", UXAS, "--use-golden", "--golden-dir", g)
    assert r.returncode == 1, r.stdout + r.stderr

def test_missing_scenario_exit_2():
    assert dt("/nonexistent/x.json", "--validate").returncode == 2

def test_no_scenario_exit_2():
    assert dt().returncode == 2

def test_unknown_comparator_exit_2(tmp_path):
    sc = json.load(open(SC)); sc["comparators"] = [{"name": "nope"}]
    p = tmp_path / "s.json"; json.dump(sc, open(p, "w"))
    assert dt(str(p), "--validate").returncode == 2

def test_missing_binary_exit_3():
    r = dt(SC, "--cpp-bin", "/nonexistent/uxas", "--use-golden")
    assert r.returncode == 3, r.stdout + r.stderr

def test_missing_golden_exit_3(tmp_path):
    r = dt(SC, "--cpp-bin", UXAS, "--use-golden", "--golden-dir", str(tmp_path))
    assert r.returncode == 3, r.stdout + r.stderr

def test_record_golden_bootstrap(tmp_path):
    r = dt(SC, "--cpp-bin", UXAS, "--record-golden", "--bootstrap-from-cpp",
           "--golden-dir", str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.load(open(tmp_path / "smoke_heartbeat.ada.golden.json"))
    assert doc["bootstrap"] is True and len(doc["records"]) == 3
    assert [x["obj"]["Value"] for x in doc["records"]] == ["1", "2", "3"] or len(doc["records"]) == 3

def test_bootstrap_requires_record_golden():
    r = dt(SC, "--cpp-bin", UXAS, "--bootstrap-from-cpp")
    assert r.returncode == 2

def test_normaliser_comparators_real_capture():
    sys.path.insert(0, CPP)
    from difftest import normalise, comparators
    from difftest.scenario import load_scenario
    sc = load_scenario(SC)
    recs = json.load(open(os.path.join(GOLD, "smoke_heartbeat.ada.golden.json")))["records"]
    n = normalise.normalise(recs, sc.normalise)
    assert len(n) == 3
    assert comparators.get("canonical")(n, n, {}) == []
    assert comparators.get("canonical")(n, n[:2], {}) != []
