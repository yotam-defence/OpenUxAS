import pytest

from difftest.comparators import (ComparatorRegistry, DEFAULT_REGISTRY,
                                  Difference, compare_captures,
                                  compare_messages, comparator, diff_values,
                                  load_plugin)


def msg(typ="x.A", fields=None, service=None):
    return {"type": typ, "address": typ, "content_type": "lmcp",
            "source_group": "", "source_entity_id": 100, "service": service,
            "fields": fields or {}}


def reg():
    return DEFAULT_REGISTRY.clone()


def test_diff_values_paths_and_kinds():
    d = diff_values({"a": 1, "b": [1, 2], "c": {"d": 1}},
                    {"a": 2, "b": [1], "c": {"e": 1}})
    kinds = {(k, p) for k, p, _, _ in d}
    assert ("value", "a") in kinds
    assert ("length", "b") in kinds
    assert ("missing_field", "c.d") in kinds
    assert ("extra_field", "c.e") in kinds


def test_default_equal_and_different():
    r = reg()
    assert compare_messages([msg(fields={"v": 1})], [msg(fields={"v": 1})],
                            r, "w") == []
    (d,) = compare_messages([msg(fields={"v": 1})], [msg(fields={"v": 2})],
                            r, "w")
    assert d.kind == "value" and d.path == "fields.v" and d.window == "w"
    assert "expected 1, actual 2" in str(d)


def test_missing_extra_and_count():
    r = reg()
    ds = compare_messages([msg("x.A"), msg("x.B")], [msg("x.A"), msg("x.C")],
                          r, "w")
    kinds = sorted((d.kind, d.msg_type) for d in ds)
    assert ("missing_message", "x.B") in kinds
    assert ("extra_message", "x.C") in kinds
    assert ("count", "x.B") in kinds and ("count", "x.C") in kinds


def test_multiset_pairing_independent_of_order():
    r = reg()
    e = [msg(fields={"v": 1}), msg(fields={"v": 2})]
    a = [msg(fields={"v": 2}), msg(fields={"v": 1})]
    assert compare_messages(e, a, r, "w") == []


def test_ordered_window_detects_reordering():
    r = reg()
    e = [msg("x.A"), msg("x.B")]
    a = [msg("x.B"), msg("x.A")]
    assert compare_messages(e, a, r, "w", ordered=False) == []
    assert compare_messages(e, a, r, "w", ordered=True)


def test_float_tolerance_binding_with_options():
    r = reg()
    r.bind_named("float_tolerance", message_type="A",
                 options={"rel": 1e-2, "abs": 0.0})
    assert compare_messages([msg(fields={"v": 1.000})],
                            [msg(fields={"v": 1.005})], r, "w") == []
    assert compare_messages([msg("x.B", {"v": 1.000})],
                            [msg("x.B", {"v": 1.005})], r, "w")


def test_resolution_specificity():
    r = ComparatorRegistry()
    r.bind(None, "S", lambda e, a: ["service"])
    assert r.resolve(msg(service="S"))(None, None) == ["service"]
    r.bind("A", None, lambda e, a: ["type"])
    assert r.resolve(msg(service="S"))(None, None) == ["type"]
    r.bind("A", "S", lambda e, a: ["both"])
    assert r.resolve(msg(service="S"))(None, None) == ["both"]
    assert r.resolve(msg(service="Z"))(None, None) == ["type"]
    assert r.resolve(msg("y.Other")) is r.default
    # full type names bind too
    r2 = ComparatorRegistry()
    r2.bind("x.A", None, lambda e, a: ["full"])
    assert r2.resolve(msg("x.A"))(None, None) == ["full"]


def test_ignore_and_ignore_fields():
    r = reg()
    r.bind_named("ignore", message_type="A")
    assert compare_messages([msg(fields={"v": 1})], [msg(fields={"v": 2})],
                            r, "w") == []
    r2 = reg()
    r2.bind_named("ignore_fields", message_type="A",
                  options={"fields": ["v"]})
    assert compare_messages([msg(fields={"v": 1, "k": 1})],
                            [msg(fields={"v": 2, "k": 1})], r2, "w") == []
    assert compare_messages([msg(fields={"v": 1, "k": 1})],
                            [msg(fields={"v": 2, "k": 2})], r2, "w")


def test_unknown_named_comparator():
    with pytest.raises(KeyError):
        reg().bind_named("nope")


def test_decorator_registers_and_plugin_loading(tmp_path):
    local = ComparatorRegistry()

    @comparator("always_diff", message_type="A", registry=local)
    def always_diff(expected, actual, **o):
        return [Difference("", "value", "x", 1, 2)]

    assert "always_diff" in local.named
    assert compare_messages([msg()], [msg()], local, "w")

    plug = tmp_path / "myplug.py"
    plug.write_text(
        "from difftest.comparators import comparator\n"
        "@comparator('plug_cmp', message_type='PlugType')\n"
        "def plug_cmp(e, a, **o):\n    return []\n")
    try:
        load_plugin(str(plug))
        assert "plug_cmp" in DEFAULT_REGISTRY.named
    finally:
        DEFAULT_REGISTRY.named.pop("plug_cmp", None)
        DEFAULT_REGISTRY.bindings = [b for b in DEFAULT_REGISTRY.bindings
                                     if b[0] != "PlugType"]


def test_compare_captures_window_mismatch():
    ds = compare_captures({"w1": [msg()]}, {"w2": [msg()]}, reg())
    assert {d.window for d in ds} == {"w1", "w2"}
    assert compare_captures({"w": [msg()]}, {"w": [msg()]}, reg()) == []
