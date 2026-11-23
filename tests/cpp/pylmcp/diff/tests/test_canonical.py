from pylmcp.diff.canonical import CanonSettings, canonicalise
from pylmcp.diff.messages import DecodedMessage, decode_frame, parse_envelope
from helpers import kv_frame


def M(type_="afrl.cmasi.X", window=0, service=1, entity=100, **fields):
    return DecodedMessage(type=type_, fields=fields, window=window,
                          source_service_id=service,
                          source_entity_id=entity)


def keys(res, w=0):
    return [c.key for c in res[w]]


def test_timestamps_and_ids_stripped_recursively():
    a = M(Time=1, RequestID=5, Inner={"TimeStamp": 9, "V": 1}, L=[{"Time": 3, "V": 2}])
    b = M(Time=2, RequestID=6, Inner={"TimeStamp": 8, "V": 1}, L=[{"Time": 4, "V": 2}])
    assert keys(canonicalise([a])) == keys(canonicalise([b]))
    c = M(Time=2, RequestID=6, Inner={"TimeStamp": 8, "V": 99}, L=[])
    assert keys(canonicalise([a])) != keys(canonicalise([c]))


def test_service_id_ignored_by_default_and_optional():
    a, b = M(service=1, V=1), M(service=2, V=1)
    assert keys(canonicalise([a])) == keys(canonicalise([b]))
    s = CanonSettings(keep_service_id=True)
    assert keys(canonicalise([a], s)) != keys(canonicalise([b], s))


def test_source_entity_kept_unless_disabled():
    a, b = M(entity=1, V=1), M(entity=2, V=1)
    assert keys(canonicalise([a])) != keys(canonicalise([b]))
    s = CanonSettings(keep_source_entity=False)
    assert keys(canonicalise([a], s)) == keys(canonicalise([b], s))


def test_sorted_within_window_but_windows_distinct():
    x, y = M("a.B", V=1), M("a.A", V=2)
    assert keys(canonicalise([x, y])) == keys(canonicalise([y, x]))
    assert [c.type for c in canonicalise([x, y])[0]] == ["a.A", "a.B"]
    r1 = canonicalise([M(V=1, window=0), M(V=2, window=1)])
    r2 = canonicalise([M(V=1, window=1), M(V=2, window=0)])
    assert keys(r1, 0) != keys(r2, 0)


def test_duplicates_preserved():
    assert len(canonicalise([M(V=1), M(V=1)])[0]) == 2


def test_float_rounding_and_nan():
    s = CanonSettings(float_digits=3)
    assert keys(canonicalise([M(V=1.00001)], s)) == \
        keys(canonicalise([M(V=1.000004)], s))
    assert keys(canonicalise([M(V=-0.0)])) == keys(canonicalise([M(V=0.0)]))
    assert "NaN" in keys(canonicalise([M(V=float("nan"))]))[0]


def test_remap_ids_preserves_cross_references_order_independent():
    s = CanonSettings(id_mode="remap")
    a1, a2 = M("t.A", RequestID=100, V=1), M("t.B", RequestID=100, V=2)
    b1, b2 = M("t.A", RequestID=777, V=1), M("t.B", RequestID=777, V=2)
    assert keys(canonicalise([a1, a2], s)) == keys(canonicalise([b2, b1], s))
    c2 = M("t.B", RequestID=778, V=2)      # broken cross reference
    assert keys(canonicalise([a1, a2], s)) != keys(canonicalise([b1, c2], s))


def test_real_frame_decode_roundtrip():
    f = kv_frame("heartbeat", "1", entity=7, service=3)
    assert parse_envelope(f)[4:] == (7, 3)
    m = decode_frame(f, window=2)
    assert m.type == "afrl.cmasi.KeyValuePair"
    assert m.fields == {"Key": "heartbeat", "Value": "1"}
    assert m.window == 2 and m.source_entity_id == 7
