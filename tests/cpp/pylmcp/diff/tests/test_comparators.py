import textwrap

import pytest

from pylmcp.diff.canonical import CanonSettings
from pylmcp.diff.comparators import (Comparator, ComparatorSet,
                                     load_comparator_class)
from pylmcp.diff.differ import diff_messages
from pylmcp.diff.messages import DecodedMessage
from pylmcp.diff.scenario import ComparatorRule


def M(type_="a.T", window=0, **fields):
    return DecodedMessage(type=type_, fields=fields, window=window)


def run(ref, got, rules=()):
    return diff_messages("s", ref, got, ComparatorSet(rules))


def test_exact_match_ignores_order_and_ids():
    r = [M(V=1, Time=1), M("a.U", V=2)]
    g = [M("a.U", V=2, Time=9), M(V=1, Time=5)]
    assert run(r, g).ok


def test_exact_reports_missing_unexpected_and_window():
    res = run([M(V=1), M(V=2, window=1)], [M(V=1), M(V=3, window=1)])
    kinds = sorted((d.window, d.kind) for d in res.differences)
    assert kinds == [(1, "missing"), (1, "unexpected")]
    assert not res.ok and "MISMATCH" in res.format()


def test_duplicate_count_difference():
    assert not run([M(V=1), M(V=1)], [M(V=1)]).ok


def test_ignore_and_exclude_types():
    rules = [ComparatorRule(["a.Noise"], "ignore")]
    assert run([M("a.Noise", V=1)], [M("a.Noise", V=2)], rules).ok
    res = diff_messages("s", [M("a.Noise")], [], ComparatorSet(),
                        exclude_types=["a.Noise"])
    assert res.ok


def test_types_only():
    rules = [ComparatorRule(["T"], "types_only")]     # short-name glob
    assert run([M(V=1)], [M(V=2)], rules).ok
    res = run([M(V=1)], [], rules)
    assert res.differences[0].kind == "count"


def test_ignore_fields_option():
    rules = [ComparatorRule(["a.*"], "exact", {"ignore_fields": ["Junk"]})]
    assert run([M(V=1, Junk=1)], [M(V=1, Junk=2)], rules).ok
    assert not run([M(V=1, Junk=1)], [M(V=2, Junk=1)], rules).ok


def test_tolerance():
    rules = [ComparatorRule(["a.T"], "tolerance", {"abs": 0.01})]
    sc = CanonSettings(float_digits=9)
    ok = diff_messages("s", [M(X=1.0, L=[1.0, 2.0])],
                       [M(X=1.005, L=[1.0, 2.004])], ComparatorSet(rules), sc)
    assert ok.ok
    bad = diff_messages("s", [M(X=1.0)], [M(X=1.5)], ComparatorSet(rules), sc)
    assert bad.differences[0].kind == "changed"
    extra = diff_messages("s", [M(X=1.0)], [M(X=1.0), M(X=2.0)],
                          ComparatorSet(rules), sc)
    assert [d.kind for d in extra.differences] == ["unexpected"]
    # strings must still match exactly
    assert not diff_messages("s", [M(S="a")], [M(S="b")],
                             ComparatorSet(rules), sc).ok


def test_first_matching_rule_wins():
    rules = [ComparatorRule(["a.T"], "ignore"),
             ComparatorRule(["a.*"], "exact")]
    assert run([M(V=1)], [M(V=2)], rules).ok
    assert not run([M("a.O", V=1)], [M("a.O", V=2)], rules).ok


def test_plugin_by_file(tmp_path):
    p = tmp_path / "plug.py"
    p.write_text(textwrap.dedent("""
        from pylmcp.diff.comparators import Comparator, Difference
        class Count(Comparator):
            def compare(self, window, ref, got):
                n = self.options.get("n", 1)
                return [] if len(ref) == len(got) == n else \\
                    [Difference(window, "count", "x", "bad")]
    """))
    spec = "%s:Count" % p
    assert issubclass(load_comparator_class(spec), Comparator)
    rules = [ComparatorRule(["a.T"], spec, {"n": 2})]
    assert run([M(V=1), M(V=2)], [M(V=8), M(V=9)], rules).ok
    assert not run([M(V=1)], [M(V=1)], rules).ok


def test_plugin_by_module_and_errors():
    cls = load_comparator_class("pylmcp.diff.comparators:ExactComparator")
    assert cls.name == "exact"
    with pytest.raises(ValueError):
        load_comparator_class("nonexistent")
    with pytest.raises(ValueError):
        load_comparator_class("pylmcp.diff.comparators:Difference")
