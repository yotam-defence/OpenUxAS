import copy
import json
import os

import pytest

from difftest.model import DelayStep, SendStep, WindowStep
from difftest.scenario import (ScenarioError, find_scenarios, load_scenario,
                               parse_scenario, scenario_digest)

SCENARIO_DIR = os.path.join(os.path.dirname(__file__), "..", "scenarios")

BASE = {
    "name": "t",
    "steps": [
        {"send": {"type": "KeyValuePair", "fields": {"Key": "a"}}},
        {"delay_ms": 10},
        {"expect_window": {"name": "w1", "duration_ms": 20}},
    ],
}


def mk(**over):
    d = copy.deepcopy(BASE)
    d.update(over)
    return d


def test_parse_minimal():
    sc = parse_scenario(BASE)
    assert sc.name == "t"
    assert [type(s) for s in sc.steps] == [SendStep, DelayStep, WindowStep]
    assert sc.windows[0].duration_ms == 20
    assert sc.startup_settle_ms == 1500


def test_bundled_scenarios_load():
    paths = find_scenarios(SCENARIO_DIR)
    assert paths
    for p in paths:
        sc = load_scenario(p)
        assert sc.windows
    # smoke scenario must not contain an AutomationRequest
    smoke = load_scenario(os.path.join(SCENARIO_DIR, "smoke.json"))
    assert "AutomationRequest" not in json.dumps(smoke.raw["steps"])


def test_repeat_expansion_substitutes_index():
    d = mk(steps=[
        {"send": {"type": "KeyValuePair", "repeat": 3, "interval_ms": 50,
                  "fields": {"Value": "tick-${i}"}}},
        {"expect_window": {"name": "w"}}])
    sc = parse_scenario(d)
    sends = [s for s in sc.steps if isinstance(s, SendStep)]
    delays = [s for s in sc.steps if isinstance(s, DelayStep)]
    assert [s.spec["fields"]["Value"] for s in sends] == \
        ["tick-0", "tick-1", "tick-2"]
    assert len(delays) == 2 and all(x.delay_ms == 50 for x in delays)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(name="has space"),
    lambda d: d.update(bogus=1),
    lambda d: d.update(steps=[]),
    lambda d: d.update(steps=[{"delay_ms": 5}]),                 # no window
    lambda d: d.update(steps=[{"expect_window": {"name": "w"}},
                              {"delay_ms": 5}]),                # not last
    lambda d: d.update(steps=[{"delay_ms": -1},
                              {"expect_window": {"name": "w"}}]),
    lambda d: d.update(steps=[{"delay_ms": 1, "send": {"type": "X"}},
                              {"expect_window": {"name": "w"}}]),
    lambda d: d.update(steps=[{"expect_window": {"name": "w"}},
                              {"expect_window": {"name": "w"}}]),  # dup
    lambda d: d.update(steps=[{"send": {"fields": {}}},
                              {"expect_window": {"name": "w"}}]),  # no type
    lambda d: d.update(steps=[{"send": {"type": "X", "repeat": 0}},
                              {"expect_window": {"name": "w"}}]),
    lambda d: d.update(comparators=[{"type": "X"}]),
    lambda d: d.update(config={"services": [{"type": 3}]}),
])
def test_invalid_scenarios_rejected(mutate):
    d = copy.deepcopy(BASE)
    mutate(d)
    with pytest.raises(ScenarioError):
        parse_scenario(d)


def test_service_type_per_impl():
    d = mk(config={"services": [
        {"type": {"ada": "AdaSvc", "cpp": "CppSvc"}, "attributes": {"A": 1}}]})
    svc = parse_scenario(d).config.services[0]
    assert (svc.type_ada, svc.type_cpp, svc.attributes) == \
        ("AdaSvc", "CppSvc", {"A": "1"})


def test_load_errors(tmp_path):
    with pytest.raises(ScenarioError):
        load_scenario(str(tmp_path / "missing.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ScenarioError):
        load_scenario(str(bad))


def test_digest_changes_with_content():
    a = parse_scenario(BASE)
    b = parse_scenario(mk(description="x"))
    assert scenario_digest(a) == scenario_digest(parse_scenario(BASE))
    assert scenario_digest(a) != scenario_digest(b)
