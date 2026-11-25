import base64
import io
import json
import os

import pytest

from diffharness import cli
from diffharness.comparators import (Comparator, UnknownComparator,
                                     available_comparators, compare_records,
                                     get_comparator, register_comparator)
from diffharness.config_gen import build_config
from diffharness.diffing import unified_diff
from diffharness.golden import (GoldenError, load_golden, save_golden)
from diffharness.normalise import NormaliseOptions, normalise
from diffharness.scenario import (ComparatorSpec, ScenarioError, load_scenario,
                                  parse_scenario)

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.join(os.path.dirname(HERE), "scenarios")
GOLD = os.path.join(os.path.dirname(HERE), "golden")


def rec(t, typ, ms=0, **fields):
    obj = {"$type": typ}
    obj.update(fields)
    return {"t_ms": t, "address": typ, "descriptor": typ,
            "content_type": "lmcp", "source_group": "",
            "source_entity_id": 100, "source_service_id": ms, "obj": obj}


def minimal(**over):
    d = {"name": "x", "capture": {"subscribe": ["a"]}, "replay": []}
    d.update(over)
    return d


# ---- normaliser -----------------------------------------------------------

def test_strips_timestamps_and_service_id():
    a = [rec(5, "T", ms=3, Time=1, Key="k", EntityIDTime=9)]
    b = [rec(99, "T", ms=8, Time=2, Key="k", EntityIDTime=1)]
    assert normalise(a) == normalise(b)
    assert "Time" not in normalise(a)[0]["obj"]


def test_value_differences_survive():
    assert normalise([rec(0, "T", Key="a")]) != normalise([rec(0, "T", Key="b")])


def test_sort_within_window_is_order_independent():
    x, y = rec(1, "A", V=1), rec(2, "B", V=2)
    assert normalise([x, y]) == normalise([y, x])


def test_windows_preserve_cross_window_order():
    x, y = rec(0, "B"), rec(1500, "A")
    n = normalise([y, x], NormaliseOptions(window_ms=1000))
    assert [m["type"] for m in n] == ["B", "A"]
    assert [m["window"] for m in n] == [0, 1]


def test_id_remapping_checks_correlation_not_value():
    a = [rec(0, "R", ResponseID=7, Other=1), rec(1, "S", ResponseID=7)]
    b = [rec(0, "R", ResponseID=99, Other=1), rec(1, "S", ResponseID=99)]
    c = [rec(0, "R", ResponseID=99, Other=1), rec(1, "S", ResponseID=98)]
    assert normalise(a) == normalise(b)
    assert normalise(a) != normalise(c)


def test_float_rounding_and_negative_zero():
    a = normalise([rec(0, "T", X=1.00000001, Y=-0.0)])
    b = normalise([rec(0, "T", X=1.0, Y=0.0)])
    assert a == b


def test_nested_and_list_cleaning():
    a = normalise([rec(0, "T", L=[{"$type": "N", "Time": 5, "v": 1}])])
    assert a[0]["obj"]["L"] == [{"$type": "N", "v": 1}]


def test_ignore_types():
    n = normalise([rec(0, "A"), rec(0, "B")],
                  NormaliseOptions(ignore_types=["A"]))
    assert [m["type"] for m in n] == ["B"]


def test_bad_option_rejected():
    with pytest.raises(ValueError):
        NormaliseOptions.from_options({"bogus": 1})


# ---- comparators ----------------------------------------------------------

def test_default_registry():
    assert {"canonical", "strict"} <= set(available_comparators())
    with pytest.raises(UnknownComparator):
        get_comparator(name="nope")


def test_canonical_equal_and_diff():
    spec = ComparatorSpec()
    ok, e, a = compare_records([rec(0, "T", Time=1, K=1)],
                               [rec(5, "T", Time=2, K=1)], spec)
    assert ok and e == a
    ok, e, a = compare_records([rec(0, "T", K=1)], [rec(0, "T", K=2)], spec)
    assert not ok


def test_strict_does_not_strip():
    ok, *_ = compare_records([rec(0, "T", Time=1)], [rec(0, "T", Time=2)],
                             ComparatorSpec(name="strict"))
    assert not ok


def test_plugin_registration_and_by_type_routing():
    @register_comparator("_test_ignore_k")
    class IgnoreK(Comparator):
        def normalise(self, records):
            for r in records:
                r["obj"].pop("K", None)
            return super().normalise(records)

    spec = ComparatorSpec(by_type={"Special": ComparatorSpec(
        name="_test_ignore_k")})
    ok, *_ = compare_records([rec(0, "Special", K=1), rec(0, "Other", K=1)],
                             [rec(0, "Special", K=2), rec(0, "Other", K=1)],
                             spec)
    assert ok
    ok, *_ = compare_records([rec(0, "Other", K=1)], [rec(0, "Other", K=2)],
                             spec)
    assert not ok


def test_duplicate_registration_rejected():
    with pytest.raises(ValueError):
        @register_comparator("canonical")
        class Dup(Comparator):
            pass


# ---- diff -----------------------------------------------------------------

def test_unified_diff_format():
    d = unified_diff(["a", "b"], ["a", "c"], "ada", "cpp")
    assert d.startswith("--- ada\n+++ cpp\n")
    assert "-b\n" in d and "+c\n" in d
    assert unified_diff(["a"], ["a"]) == ""


# ---- scenario loader / config --------------------------------------------

def test_smoke_scenario_loads():
    sc = load_scenario(os.path.join(SCEN, "smoke_heartbeat.json"))
    assert sc.name == "smoke_heartbeat"
    assert len(sc.replay) == 4 and sc.replay[1].delay_ms == 250
    assert all(s.type != "AutomationRequest" for s in sc.replay)


@pytest.mark.parametrize("bad", [
    {"name": "x"},                                         # no capture
    minimal(bogus=1),
    minimal(replay=[{"type": "T", "raw_b64": "AA==", "address": "a"}]),
    minimal(replay=[{"delay_ms": -1, "type": "T"}]),
    minimal(replay=[{"delay_ms": 0}]),
    minimal(replay=[{"raw_b64": "!!!", "address": "a"}]),
    minimal(replay=[{"raw_b64": "AA=="}]),                 # no address
    minimal(services=[{"nope": 1}]),
    minimal(services=[{"Type": "S", "impl": "rust"}]),
    minimal(comparator={"bad": 1}),
])
def test_invalid_scenarios(bad):
    with pytest.raises(ScenarioError):
        parse_scenario(bad)


def test_raw_step_and_defaults():
    sc = parse_scenario(minimal(replay=[
        {"raw_b64": base64.b64encode(b"\x01").decode(), "address": "a"}]))
    assert sc.replay[0].raw == b"\x01" and sc.replay[0].delay_ms == 0
    assert sc.comparator.name == "canonical"


def test_missing_scenario_file():
    with pytest.raises(ScenarioError):
        load_scenario("/nonexistent.json")


def test_config_per_impl_filter_and_bridge():
    sc = parse_scenario(minimal(
        capture={"subscribe": ["afrl.cmasi.KeyValuePair"]},
        services=[{"Type": "Common"},
                  {"Type": "OnlyAda", "impl": "ada", "Flag": True}]))
    cpp = build_config(sc, "cpp").decode()
    ada = build_config(sc, "ada").decode()
    assert "OnlyAda" not in cpp and 'Flag="TRUE"' in ada
    hub = build_config(sc, "ada", role="hub").decode()
    # uxas_ada is only a client of the C++ hub: shared services live in the
    # hub, Ada-only services in the uxas_ada config.
    assert 'Type="Common"' in cpp and 'Type="Common"' in hub
    assert 'Type="Common"' not in ada and "OnlyAda" not in hub
    for x in (cpp, ada, hub):
        assert "LmcpObjectNetworkPublishPullBridge" in x
        assert 'MessageType="afrl.cmasi.KeyValuePair"' in x
    with pytest.raises(ValueError):
        build_config(sc, "rust")


def test_wildcard_subscription():
    sc = parse_scenario(minimal(capture={"subscribe": ["*"]}))
    assert build_config(sc, "cpp").count(b"SubscribeToMessage") == 52


# ---- golden + CLI ---------------------------------------------------------

def test_golden_roundtrip(tmp_path):
    save_golden(str(tmp_path), "s", "ada", [rec(0, "T")])
    assert load_golden(str(tmp_path), "s", "ada") == [rec(0, "T")]
    with pytest.raises(GoldenError):
        load_golden(str(tmp_path), "s", "cpp")


def test_committed_goldens_equivalent():
    sc = load_scenario(os.path.join(SCEN, "smoke_heartbeat.json"))
    ada = load_golden(GOLD, sc.name, "ada")
    cpp = load_golden(GOLD, sc.name, "cpp")
    out = io.StringIO()
    assert cli.report(sc, ada, cpp, "ada(golden)", out) == cli.EXIT_OK
    assert out.getvalue().startswith("PASS")


def test_report_mismatch_exit_and_diff():
    sc = load_scenario(os.path.join(SCEN, "smoke_heartbeat.json"))
    ada = load_golden(GOLD, sc.name, "ada")
    cpp = json.loads(json.dumps(load_golden(GOLD, sc.name, "cpp")))
    cpp[0]["obj"]["Value"] = "CHANGED"
    out = io.StringIO()
    assert cli.report(sc, ada, cpp, "ada(golden)", out) == cli.EXIT_MISMATCH
    assert "--- ada(golden)" in out.getvalue() and "CHANGED" in out.getvalue()


def test_cli_dry_run_and_errors(capsys):
    assert cli.main(["--scenario", "smoke_heartbeat", "--dry-run"]) == 0
    assert "LmcpObjectNetworkPublishPullBridge" in capsys.readouterr().out
    assert cli.main(["--scenario", "smoke_heartbeat"]) == cli.EXIT_ERROR
    assert "--cpp-bin" in capsys.readouterr().err
    assert cli.main(["--scenario", "smoke_heartbeat",
                     "--cpp-bin", "x"]) == cli.EXIT_ERROR
    assert "--ada-bin" in capsys.readouterr().err
    assert cli.main(["--scenario", "/nonexistent"]) == cli.EXIT_ERROR
    assert cli.main(["--list-comparators"]) == 0
    assert "canonical" in capsys.readouterr().out
