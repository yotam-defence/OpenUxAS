from difftest.normalise import (IdRenumberer, NormaliserConfig,
                                assign_windows, canonical_value,
                                normalise_capture, normalise_window,
                                short_type, type_matches)


def rec(typ="afrl.cmasi.KeyValuePair", fields=None, t=0.0, svc=7, ent=100):
    return {"address": typ, "descriptor": typ, "content_type": "lmcp",
            "source_group": "", "source_entity_id": ent,
            "source_service_id": svc, "type": typ,
            "fields": fields or {}, "t": t}


def test_short_type_and_match():
    assert short_type("afrl.cmasi.KeyValuePair") == "KeyValuePair"
    assert type_matches("afrl.cmasi.KeyValuePair", ["KeyValuePair"])
    assert type_matches("afrl.cmasi.KeyValuePair", ["afrl.cmasi.KeyValuePair"])
    assert not type_matches("afrl.cmasi.KeyValuePair", ["Pair"])


def test_strip_volatile_fields_any_depth():
    cfg = NormaliserConfig(strip_fields=["Secret"])
    out = canonical_value({"Time": 5, "Secret": 1, "Keep": 2,
                           "N": [{"TimeSent": 9, "x": 1}]}, cfg)
    assert out == {"Keep": 2, "N": [{"x": 1}]}


def test_float_canonicalisation():
    cfg = NormaliserConfig(float_digits=4)
    assert canonical_value(1.2345678, cfg) == 1.235
    assert canonical_value(-0.0, cfg) == 0.0
    assert canonical_value(float("nan"), cfg) == "NaN"
    assert canonical_value(float("-inf"), cfg) == "-Inf"
    assert canonical_value(b"\x01\xff", cfg) == "01ff"
    assert canonical_value(True, cfg) is True
    assert canonical_value(3, cfg) == 3


def test_header_noise_dropped_and_service_mapped():
    cfg = NormaliserConfig(service_names={"7": "Router"})
    (m,) = normalise_window([rec(svc=7)], cfg)
    assert "source_service_id" not in m
    assert m["service"] == "Router"
    assert m["source_entity_id"] == 100
    cfg2 = NormaliserConfig(strip_header=["source_entity_id"])
    (m2,) = normalise_window([rec(svc=9, ent=5)], cfg2)
    assert "source_entity_id" not in m2 and m2["service"] is None


def test_equal_modulo_timestamps_and_service_id():
    cfg = NormaliserConfig()
    a = normalise_window([rec(fields={"Time": 1, "V": 2}, svc=1)], cfg)
    b = normalise_window([rec(fields={"Time": 999, "V": 2}, svc=44)], cfg)
    assert a == b
    c = normalise_window([rec(fields={"Time": 1, "V": 3})], cfg)
    assert a != c


def test_window_sorted_by_type_unless_ordered():
    cfg = NormaliserConfig()
    r = [rec("b.B", {"x": 2}), rec("a.A", {"x": 9}), rec("b.B", {"x": 1})]
    out = normalise_window(r, cfg)
    assert [(m["type"], m["fields"]["x"]) for m in out] == \
        [("a.A", 9), ("b.B", 1), ("b.B", 2)]
    # arrival order must not matter
    assert normalise_window(list(reversed(r)), cfg) == out
    ordered = normalise_window(r, cfg, ordered=True)
    assert [m["type"] for m in ordered] == ["b.B", "a.A", "b.B"]


def test_ignore_and_types_filter():
    cfg = NormaliserConfig(ignore_types=["Noise"])
    r = [rec("x.Noise"), rec("x.A"), rec("x.B")]
    assert [m["type"] for m in normalise_window(r, cfg)] == ["x.A", "x.B"]
    assert [m["type"] for m in normalise_window(r, cfg, types=["B"])] == \
        ["x.B"]


def test_renumber_preserves_relations_not_values():
    cfg = NormaliserConfig(renumber_fields=["CommandID"])
    ada = normalise_capture({"w": [rec("x.A", {"CommandID": 41, "n": 1}),
                                   rec("x.B", {"CommandID": 41}),
                                   rec("x.A", {"CommandID": 42, "n": 2})]},
                            cfg)
    cpp = normalise_capture({"w": [rec("x.A", {"CommandID": 9001, "n": 1}),
                                   rec("x.B", {"CommandID": 9001}),
                                   rec("x.A", {"CommandID": 9002, "n": 2})]},
                            cfg)
    assert ada == cpp
    # a broken relation (B refers to another command) must be detected
    bad = normalise_capture({"w": [rec("x.A", {"CommandID": 9001, "n": 1}),
                                   rec("x.B", {"CommandID": 9002}),
                                   rec("x.A", {"CommandID": 9002, "n": 2})]},
                            cfg)
    assert bad != ada


def test_renumberer_is_stable_across_windows():
    r = IdRenumberer(["ID"])
    assert r.apply({"ID": 5}) == {"ID": "<ID#1>"}
    assert r.apply({"ID": 6}) == {"ID": "<ID#2>"}
    assert r.apply({"ID": 5, "l": [{"ID": 6}]}) == \
        {"ID": "<ID#1>", "l": [{"ID": "<ID#2>"}]}


def test_assign_windows():
    recs = [rec(t=0.5), rec(t=1.0), rec(t=1.5), rec(t=2.5), rec(t=9.0)]
    out = assign_windows(recs, [("a", 2.0), ("b", 3.0)], start_t=1.0)
    assert "__startup__" not in out
    assert [r["t"] for r in out["a"]] == [1.0, 1.5]
    assert [r["t"] for r in out["b"]] == [2.5]
    assert [r["t"] for r in out["__trailing__"]] == [9.0]
    out2 = assign_windows(recs, [("a", 2.0), ("b", 3.0)], 1.0,
                          capture_startup=True)
    assert [r["t"] for r in out2["__startup__"]] == [0.5]


def test_config_from_dict_rejects_unknown():
    import pytest
    with pytest.raises(ValueError):
        NormaliserConfig.from_dict({"nope": 1})


def test_replace_defaults():
    cfg = NormaliserConfig.from_dict({"strip_fields": ["A"],
                                      "replace_defaults": True})
    assert cfg.strip_fields == {"A"} and not cfg.renumber_fields
