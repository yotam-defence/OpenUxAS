"""Pure-python unit tests: no Ada/C++ binary, no zmq, no pylmcp needed."""
import json
import os

import pytest

from difftest import canon, comparators, golden, scenario
from difftest.cli import DEFAULT_GOLDEN_DIR, main
from difftest.report import compare

SCEN_DIR = os.path.join(os.path.dirname(__file__), "..", "scenarios")
SMOKE = os.path.join(SCEN_DIR, "smoke_heartbeat.json")


def msg(desc, obj, t=0.0, **kw):
    d = {"t_ms": t, "descriptor": desc, "content_type": "lmcp",
         "source_entity_id": 100, "source_service_id": 0, "obj": obj}
    d.update(kw)
    return d


# ---------------------------------------------------------------- scenario
def test_load_smoke_scenario():
    sc = scenario.load(SMOKE)
    assert sc.name == "smoke_heartbeat"
    assert len(sc.messages) == 3
    assert all(m.type == "afrl.cmasi.KeyValuePair" for m in sc.messages)
    assert sc.messages[0].source_entity_id == 100
    assert "AutomationRequest" not in json.dumps(sc.messages[0].fields)
    for b in ("ada", "cpp"):
        assert "${PUB_ADDRESS}" in sc.config_template(b)


def test_render_template():
    out = scenario.render_template("a=${X} b=${Y}", X=1, Y="z")
    assert out == "a=1 b=z"
    with pytest.raises(scenario.ScenarioError):
        scenario.render_template("${NOPE}", X=1)


@pytest.mark.parametrize("data", [
    {},
    {"name": "x", "bogus": 1},
    {"name": "x", "config": {"java": "a.xml"}},
    {"name": "x", "messages": [{"fields": {}}]},
    {"name": "x", "messages": [{"type": "t", "delay_ms": -1}]},
    {"name": "x", "messages": [{"type": "t", "wat": 1}]},
])
def test_invalid_scenarios(data):
    with pytest.raises(scenario.ScenarioError):
        scenario.from_dict(data)


def test_scenario_defaults_entity_id_for_messages():
    sc = scenario.from_dict({"name": "x", "entity_id": 7,
                             "messages": [{"type": "a.B"}]})
    assert sc.messages[0].source_entity_id == 7
    assert sc.messages[0].delay_ms == 100


def test_missing_config_template(tmp_path):
    sc = scenario.from_dict({"name": "x", "config": {"ada": "nope.xml"}})
    with pytest.raises(scenario.ScenarioError):
        sc.config_template("ada")
    with pytest.raises(scenario.ScenarioError):
        sc.config_template("cpp")


# ----------------------------------------------------------- canonicaliser
def test_strips_time_and_source_ids_and_timing():
    a = [msg("a.B", {"Time": 5, "V": 1}, t=10, source_entity_id=1)]
    b = [msg("a.B", {"Time": 99, "V": 1}, t=999, source_entity_id=2)]
    assert canon.canonicalise(a) == canon.canonicalise(b)


def test_strip_is_recursive():
    a = [msg("a.B", {"Inner": [{"Time": 1, "V": 2}]})]
    assert canon.canonicalise(a)[0]["obj"] == {"Inner": [{"V": 2}]}


def test_sorting_ignores_arrival_order():
    x, y = msg("a.X", {"V": 1}, t=1), msg("a.Y", {"V": 2}, t=2)
    assert canon.canonicalise([x, y]) == canon.canonicalise([y, x])


def test_sort_window_buckets_preserve_window_order():
    cfg = canon.CanonConfig(sort_window_ms=100)
    early_z = msg("z.Z", {}, t=0)
    late_a = msg("a.A", {}, t=500)
    out = canon.canonicalise([late_a, early_z], cfg)
    assert [m["descriptor"] for m in out] == ["z.Z", "a.A"]
    out_all = canon.canonicalise([late_a, early_z])
    assert [m["descriptor"] for m in out_all] == ["a.A", "z.Z"]


def test_remap_fields_consistent_ordinals():
    cfg = canon.CanonConfig(remap_fields=["RequestID"])
    a = [msg("a.Req", {"RequestID": 41}, t=1),
         msg("a.Resp", {"RequestID": 41}, t=2),
         msg("a.Req", {"RequestID": 77}, t=3)]
    b = [msg("a.Req", {"RequestID": 1001}, t=1),
         msg("a.Resp", {"RequestID": 1001}, t=2),
         msg("a.Req", {"RequestID": 1002}, t=3)]
    assert canon.canonicalise(a, cfg) == canon.canonicalise(b, cfg)
    # but distinct ids must stay distinct
    c = [msg("a.Req", {"RequestID": 1}, t=1), msg("a.Resp", {"RequestID": 2}, t=2),
         msg("a.Req", {"RequestID": 3}, t=3)]
    assert canon.canonicalise(a, cfg) != canon.canonicalise(c, cfg)


def test_float_rounding_and_negative_zero():
    cfg = canon.CanonConfig(float_digits=3)
    out = canon.canonicalise([msg("a.B", {"x": 1.00049, "z": -0.0})], cfg)
    assert out[0]["obj"] == {"x": 1.0, "z": 0.0}


def test_keep_order_descriptors():
    cfg = canon.CanonConfig(keep_order_descriptors=["z.Z"])
    msgs = [msg("z.Z", {"n": 2}, t=1), msg("z.Z", {"n": 1}, t=2),
            msg("a.A", {}, t=3)]
    out = canon.canonicalise(msgs, cfg)
    assert [m["obj"].get("n") for m in out if m["descriptor"] == "z.Z"] == [2, 1]


def test_filter_capture():
    msgs = [msg("a.B", {}), msg("a.C", {}), msg("x.Y", {})]
    assert [m["descriptor"] for m in
            canon.filter_capture(msgs, include=["a.*"], exclude=["a.C"])] == ["a.B"]


def test_bad_canonical_key():
    with pytest.raises(ValueError):
        canon.CanonConfig.from_dict({"nope": 1})


# ------------------------------------------------------------- comparators
def test_exact_detects_difference_and_multiplicity():
    a = canon.canonicalise([msg("a.B", {"v": 1}), msg("a.B", {"v": 1})])
    b = canon.canonicalise([msg("a.B", {"v": 1})])
    r = compare(a, b)
    assert not r.passed and "a.B" in r.diffs
    assert compare(a, a).passed


def test_missing_descriptor_on_one_side():
    a = canon.canonicalise([msg("a.B", {}), msg("a.C", {})])
    b = canon.canonicalise([msg("a.B", {})])
    r = compare(a, b)
    assert list(r.diffs) == ["a.C"]


def test_numeric_tolerance_comparator():
    a = canon.canonicalise([msg("a.B", {"v": 1.0, "l": [1.0, 2.0]})])
    b = canon.canonicalise([msg("a.B", {"v": 1.0004, "l": [1.0, 2.0003]})])
    assert not compare(a, b, {"*": "exact"}).passed
    assert compare(a, b, {"*": {"name": "numeric", "abs": 1e-3}}).passed
    assert not compare(a, b, {"*": {"name": "numeric", "abs": 1e-5}}).passed


def test_ignore_count_superset():
    a = canon.canonicalise([msg("a.B", {"v": 1})])
    b = canon.canonicalise([msg("a.B", {"v": 1}), msg("a.B", {"v": 2})])
    assert compare(a, b, {"a.B": "ignore"}).passed
    assert not compare(a, b, {"a.B": "count"}).passed
    assert compare(a, b, {"a.B": "cpp_superset"}).passed
    assert not compare(b, a, {"a.B": "cpp_superset"}).passed


def test_most_specific_pattern_wins():
    spec = {"*": "exact", "a.*": "count", "a.B": "ignore"}
    assert comparators.resolve("a.B", spec)[0] is comparators.get("ignore")
    assert comparators.resolve("a.C", spec)[0] is comparators.get("count")
    assert comparators.resolve("z.C", spec)[0] is comparators.get("exact")
    assert comparators.resolve("z.C", None)[0] is comparators.get("exact")


def test_unknown_comparator():
    with pytest.raises(comparators.ComparatorError):
        comparators.get("does_not_exist")


def test_plugin_registration():
    @comparators.register("only_keys")
    def only_keys(ada, cpp, params):
        ka = {k for m in ada for k in m["obj"]}
        kc = {k for m in cpp for k in m["obj"]}
        return [] if ka == kc else ["key sets differ"]

    a = canon.canonicalise([msg("s.M", {"k": 1})])
    b = canon.canonicalise([msg("s.M", {"k": 2})])
    assert compare(a, b, {"s.M": "only_keys"}).passed
    assert "only_keys" in comparators.available()


def test_load_plugin_module(tmp_path, monkeypatch):
    (tmp_path / "myplug.py").write_text(
        "from difftest.comparators import register\n"
        "@register('plug_cmp')\n"
        "def f(a, b, p):\n    return []\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    comparators.load_plugin("myplug")
    assert "plug_cmp" in comparators.available()
    with pytest.raises(comparators.ComparatorError):
        comparators.load_plugin("no_such_plugin_module")


def test_report_text_and_json():
    a = canon.canonicalise([msg("a.B", {"v": 1})])
    r = compare(a, [], scenario="s")
    assert "DIFFERENT" in r.to_text()
    assert json.loads(r.to_json())["passed"] is False


# ------------------------------------------------------------------ golden
def test_golden_roundtrip(tmp_path):
    p = golden.golden_path(str(tmp_path), "sc", "ada")
    msgs = [msg("a.B", {"v": 1})]
    golden.save(p, "sc", "ada", msgs)
    assert golden.load(p, "sc") == msgs
    with pytest.raises(golden.GoldenError):
        golden.load(p, "other")
    with pytest.raises(golden.GoldenError):
        golden.load(str(tmp_path / "missing.json"))


def test_committed_smoke_golden_loads():
    p = golden.golden_path(DEFAULT_GOLDEN_DIR, "smoke_heartbeat", "ada")
    assert golden.load(p, "smoke_heartbeat") == []


# --------------------------------------------------------------------- CLI
def test_cli_compare_offline(tmp_path, capsys):
    a, c = str(tmp_path / "a.json"), str(tmp_path / "c.json")
    golden.save(a, "s", "ada", [msg("a.B", {"Time": 1, "v": 1})])
    golden.save(c, "s", "cpp", [msg("a.B", {"Time": 2, "v": 1}, t=50)])
    assert main(["compare", a, c]) == 0
    golden.save(c, "s", "cpp", [msg("a.B", {"v": 2})])
    assert main(["compare", a, c]) == 1
    assert main(["compare", a, str(tmp_path / "nope.json")]) == 2


def test_cli_run_with_both_goldens(tmp_path):
    gdir = str(tmp_path)
    golden.save(golden.golden_path(gdir, "smoke_heartbeat", "ada"),
                "smoke_heartbeat", "ada", [])
    golden.save(golden.golden_path(gdir, "smoke_heartbeat", "cpp"),
                "smoke_heartbeat", "cpp", [])
    argv = ["run", SMOKE, "--ada-golden", "--cpp-golden",
            "--golden-dir", gdir]
    assert main(argv) == 0
    # replayed heartbeats are excluded by the scenario capture filter
    golden.save(golden.golden_path(gdir, "smoke_heartbeat", "cpp"),
                "smoke_heartbeat", "cpp",
                [msg("afrl.cmasi.KeyValuePair", {"Key": "x"})])
    assert main(argv) == 0
    golden.save(golden.golden_path(gdir, "smoke_heartbeat", "cpp"),
                "smoke_heartbeat", "cpp", [msg("uxas.messages.X", {})])
    assert main(argv) == 1


def test_cli_missing_golden_is_error(tmp_path):
    assert main(["run", SMOKE, "--ada-golden", "--cpp-golden",
                 "--golden-dir", str(tmp_path)]) == 2


def test_cli_missing_binary_is_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UXAS_CPP_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    golden.save(golden.golden_path(str(tmp_path), "smoke_heartbeat", "ada"),
                "smoke_heartbeat", "ada", [])
    assert main(["run", SMOKE, "--ada-golden", "--cpp-bin",
                 str(tmp_path / "missing"), "--golden-dir", str(tmp_path)]) == 2


def test_golden_provenance(tmp_path):
    rec = str(tmp_path / "rec.json")
    hand = str(tmp_path / "hand.json")
    golden.save(rec, "s", "ada", [])
    golden.save(hand, "s", "ada", [], provenance="hand-authored test")
    assert golden.is_recorded(rec)
    assert not golden.is_recorded(hand)
    assert not golden.is_recorded(golden.golden_path(
        DEFAULT_GOLDEN_DIR, "smoke_heartbeat", "ada"))


def test_cli_warns_on_hand_authored_golden(tmp_path, capsys):
    gdir = str(tmp_path)
    golden.save(golden.golden_path(gdir, "smoke_heartbeat", "ada"),
                "smoke_heartbeat", "ada", [], provenance="hand-authored x")
    golden.save(golden.golden_path(gdir, "smoke_heartbeat", "cpp"),
                "smoke_heartbeat", "cpp", [])
    rc = main(["run", SMOKE, "--ada-golden", "--cpp-golden",
               "--golden-dir", gdir])
    assert rc == 0
    assert "hand-authored" in capsys.readouterr().err
