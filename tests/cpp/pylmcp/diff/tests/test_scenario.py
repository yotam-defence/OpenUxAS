import copy
import os

import pytest

from pylmcp.diff.scenario import (ScenarioError, load_recording,
                                  load_scenario, parse_scenario)
from pylmcp.diff.config import build_config

SCEN_DIR = os.path.join(os.path.dirname(__file__), "..", "scenarios")

BASE = {"format_version": 1, "name": "t"}


def test_smoke_scenario_loads():
    sc = load_scenario(os.path.join(SCEN_DIR, "smoke_heartbeat.json"))
    assert sc.name == "smoke_heartbeat"
    assert len(sc.steps) == 3
    # heartbeat only: no AutomationRequest
    assert all("AutomationRequest" not in s.lmcp["type"] for s in sc.steps)


def test_all_shipped_scenarios_valid():
    for f in os.listdir(SCEN_DIR):
        if f.endswith(".json"):
            load_scenario(os.path.join(SCEN_DIR, f))


def test_defaults():
    sc = parse_scenario(BASE)
    assert sc.timing.settle_ms == 300 and sc.capture.window == "step"
    assert sc.entity_id == 100


@pytest.mark.parametrize("patch,msg", [
    ({"bogus": 1}, "unknown key"),
    ({"format_version": 2}, "format_version"),
    ({"name": "a b"}, "name"),
    ({"timing": {"settle_ms": -1}}, "settle_ms"),
    ({"timing": {"nope": 1}}, "unknown key"),
    ({"capture": {"window": "weird"}}, "capture.window"),
    ({"capture": {"echo_filter": "x"}}, "echo_filter"),
    ({"normalise": {"id_mode": "x"}}, "id_mode"),
    ({"services": [{"type": "S", "sides": ["java"]}]}, "sides"),
    ({"services": [{"attributes": {}}]}, "missing"),
    ({"replay": [{"frame_hex": "zz"}]}, "hex"),
    ({"replay": [{"frame_hex": "00", "lmcp": {"type": "x"}}]}, "exactly one"),
    ({"replay": [{"lmcp": {"fields": {}}}]}, "missing"),
    ({"comparators": [{"use": "exact"}]}, "missing"),
])
def test_invalid(patch, msg):
    d = copy.deepcopy(BASE)
    d.update(patch)
    with pytest.raises(ScenarioError) as e:
        parse_scenario(d)
    assert msg in str(e.value)


def test_invalid_json_file(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{oops")
    with pytest.raises(ScenarioError):
        load_scenario(str(p))
    with pytest.raises(ScenarioError):
        load_scenario(str(tmp_path / "missing.json"))


def test_recording_expansion(tmp_path):
    rec = tmp_path / "r.jsonl"
    rec.write_text('# c\n{"delay_ms": 5, "frame_hex": "aa"}\n\n'
                   '{"frame_hex": "bb"}\n')
    d = dict(BASE, replay=[{"recording": "r.jsonl"},
                           {"frame_hex": "cc"}])
    sc = parse_scenario(d, base_dir=str(tmp_path))
    assert [s.frame_hex for s in sc.steps] == ["aa", "bb", "cc"]
    assert sc.steps[0].delay_ms == 5
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n")
    with pytest.raises(ScenarioError):
        load_recording(str(bad))


def test_fingerprint_ignores_normalisation_but_not_services():
    a = parse_scenario(BASE)
    b = parse_scenario(dict(BASE, normalise={"float_digits": 3},
                            comparators=[{"match": "*", "use": "ignore"}]))
    c = parse_scenario(dict(BASE, services=[{"type": "S"}]))
    assert a.capture_fingerprint("ada") == b.capture_fingerprint("ada")
    assert a.capture_fingerprint("ada") != c.capture_fingerprint("ada")


def test_config_generation_and_sides():
    sc = parse_scenario(dict(BASE, services=[
        {"type": "Both", "attributes": {"A": 1, "B": True, "C": "x"}},
        {"type": "AdaOnly", "sides": ["ada"]},
        {"type": "CppOnly", "sides": ["cpp"],
         "children": [{"tag": "Sub", "attributes": {"k": 2.5}}]}]))
    ada = build_config(sc, "ada").decode()
    cpp = build_config(sc, "cpp").decode()
    assert 'Type="Both" A="1" B="TRUE" C="x"' in ada
    assert "AdaOnly" in ada and "CppOnly" not in ada
    assert "CppOnly" in cpp and "AdaOnly" not in cpp
    assert '<Sub k="2.5"' in cpp
    for x in (ada, cpp):
        assert 'AddressPUB="tcp://127.0.0.1:5560"' in x
        assert 'EntityID="100"' in x
    # valid XML
    import xml.etree.ElementTree as ET
    ET.fromstring(build_config(sc, "ada").split(b"\n", 1)[1])
