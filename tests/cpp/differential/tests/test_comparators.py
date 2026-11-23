from helpers import *  # noqa
from uxdiff import comparators as C
from uxdiff.normalise import Captured, Normaliser


def recs(*pairs, **kw):
    return Normaliser(**kw).normalise(
        [Captured(kvp_raw(k, v)) for k, v in pairs])


def test_registry_has_builtins():
    assert {"default", "heartbeat"} <= set(C.list_comparators())
    with raises(KeyError):
        C.get_comparator("nope")


def test_default_equal_and_diff():
    a = recs(("a", "1"), ("b", "2"))
    assert C.get_comparator("default").compare(a, list(a)).equal
    rep = C.get_comparator("default").compare(a, recs(("a", "1")))
    assert not rep.equal and rep.entries[0].kind == "missing"
    rep = C.get_comparator("default").compare(recs(("a", "1")), a)
    assert rep.entries[0].kind == "extra"
    rep = C.get_comparator("default").compare(recs(("a", "1")), recs(("a", "2")))
    assert rep.entries[0].kind == "changed"
    assert "changed" in rep.format()


def test_heartbeat_ignores_other_keys_and_order():
    ref = recs(("heartbeat", "1"), ("other", "x"), ("heartbeat", "2"))
    cand = recs(("heartbeat", "2"), ("heartbeat", "1"))
    assert not C.get_comparator("heartbeat").compare(ref, cand).equal
    assert C.get_comparator("heartbeat", {"keys": ["heartbeat"]}).compare(
        ref, cand).equal


def test_heartbeat_options():
    ref = recs(("heartbeat", "1"), ("heartbeat", "1"))
    cand = recs(("heartbeat", "9"))
    assert not C.get_comparator("heartbeat").compare(ref, cand).equal
    opts = {"compare_values": False, "ignore_count": True}
    assert C.get_comparator("heartbeat", opts).compare(ref, cand).equal
    assert not C.get_comparator("heartbeat", {"keys": ["heartbeat"]}).compare(
        ref, cand).equal


def test_plugin_registration_decorator_and_class():
    @C.register_comparator("unit-first-only")
    class FirstOnly(C.Comparator):
        def select(self, r):
            return r["fields"]["Key"] == "first"

    a = recs(("first", "1"), ("zzz", "1"))
    b = recs(("first", "1"), ("zzz", "2"))
    assert C.get_comparator("unit-first-only").compare(a, b).equal
    assert C.get_comparator("default").compare(a, b).equal is False

    class Other(C.Comparator):
        name = "unit-other"
    C.register_comparator(Other)
    assert "unit-other" in C.list_comparators()
    with raises(TypeError):
        C.register_comparator("bad", object)


def test_load_plugin_from_file():
    import os
    import tempfile
    src = ("from uxdiff.comparators import register_comparator, Comparator\n"
           "@register_comparator('unit-file-plugin')\n"
           "class P(Comparator):\n    pass\n")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "plug.py")
        with open(p, "w") as fd:
            fd.write(src)
        C.load_plugin(p)
    assert "unit-file-plugin" in C.list_comparators()
