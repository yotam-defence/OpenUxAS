from helpers import *  # noqa
from uxdiff import lmcp, normalise
from uxdiff.normalise import Captured, Normaliser, register_decoder


def cap(raw, step=0, t=0.0):
    return Captured(raw, t, step)


def test_strips_addresses_service_ids_and_times():
    a = Normaliser().normalise([cap(kvp_raw("k", "v", service_id=1), t=1)])
    b = Normaliser().normalise([cap(kvp_raw("k", "v", service_id=99), t=500)])
    assert a == b
    assert a[0]["fields"] == {"Key": "k", "Value": "v"}
    assert "address" not in a[0] and "source_service_id" not in a[0]


def test_sorted_by_type_content_independent_of_arrival_order():
    msgs = [kvp_raw("b", "1"), kvp_raw("a", "2"), kvp_raw("a", "1")]
    x = Normaliser().normalise([cap(m) for m in msgs])
    y = Normaliser().normalise([cap(m) for m in reversed(msgs)])
    assert x == y
    assert [r["fields"]["Value"] for r in x] == ["1", "2", "1"]


def test_window_step_keeps_windows_separate():
    caps = [cap(kvp_raw("a", "1"), step=1), cap(kvp_raw("a", "1"), step=0)]
    recs = Normaliser(window="step").normalise(caps)
    assert [r["window"] for r in recs] == [0, 1]
    assert {r["window"] for r in Normaliser().normalise(caps)} == {0}


def test_strip_field_and_float_rounding_and_id_renumbering():
    def dec(body):
        r = lmcp.Reader(body)
        return {"RequestID": r.unpack(">q"), "Time": r.unpack(">q"),
                "X": r.unpack(">d")}
    import struct
    register_decoder("TESTSER", 1, dec)

    def msg(rid, t, x):
        body = struct.pack(">qqd", rid, t, x)
        fr = lmcp.build_frame("TESTSER", 1, 1, body)
        return lmcp.Envelope("t.Type", fr).pack()

    a = Normaliser().normalise([cap(msg(777, 1, 0.1234567891)),
                                cap(msg(888, 2, 0.5))])
    b = Normaliser().normalise([cap(msg(5, 99, 0.1234567899)),
                                cap(msg(6, 98, 0.5))])
    assert a == b
    assert a[0]["fields"] == {"RequestID": "RequestID#1", "X": 0.123457}
    assert "Time" not in a[0]["fields"]


def test_unknown_type_falls_back_to_raw_body():
    fr = lmcp.build_frame("NOSUCH", 5, 1, b"\x01\x02")
    recs = Normaliser().normalise([cap(lmcp.Envelope("x.y", fr).pack())])
    assert recs[0]["raw_body"] == "0102" and "fields" not in recs[0]


def test_malformed_input_is_recorded_not_raised():
    recs = Normaliser().normalise([cap(b"garbage"),
                                   cap(lmcp.Envelope("a", b"zz").pack())])
    assert all("malformed" in r for r in recs) and len(recs) == 2


def test_exclude_echo_and_types():
    fr = lmcp.key_value_pair_frame("a", "1")
    n = Normaliser(exclude_raw=[fr])
    assert n.normalise([cap(kvp_raw("a", "1"))]) == []
    n = Normaliser(exclude_types=["afrl.cmasi.KeyValuePair"])
    assert n.normalise([cap(kvp_raw("a", "1"))]) == []
