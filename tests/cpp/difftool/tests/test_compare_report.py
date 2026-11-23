import json
import os
import unittest

from difftool import comparators as C
from difftool import normalize as n
from difftool import report as R
from .helpers import kv, tmpdir


def win(*msgs, **kw):
    return n.canonicalise(list(msgs), n.Options(**kw))


class ComparatorTests(unittest.TestCase):
    def test_identical_match(self):
        a = win(kv(0, "x"), kv(1, "y")); b = win(kv(0, "y"), kv(1, "x", service=8))
        self.assertEqual(C.get("canonical").compare(a, b), [])

    def test_missing_and_extra(self):
        a = win(kv(0, "x"), kv(1, "y", typ="afrl.cmasi.AAA"))
        b = win(kv(0, "x"), kv(1, "z", typ="afrl.cmasi.BBB"))
        kinds = sorted(d.kind for d in C.get("canonical").compare(a, b))
        self.assertEqual(kinds, [R.EXTRA_IN_CPP, R.MISSING_IN_CPP])

    def test_mismatch_has_field_path(self):
        d = C.get("canonical").compare(win(kv(0, "x")), win(kv(0, "y")))
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0].kind, R.MISMATCH)
        self.assertEqual(d[0].path, "body.Value")
        self.assertEqual((d[0].ada, d[0].cpp), ("x", "y"))

    def test_window_count_mismatch(self):
        a = win(kv(0, "x"), kv(1000, "y"), window_ms=10)
        b = win(kv(0, "x"), window_ms=10)
        d = C.get("canonical").compare(a, b)
        self.assertEqual([x.kind for x in d], [R.MISSING_IN_CPP])
        self.assertEqual(d[0].window, 1)

    def test_include_exclude_filter(self):
        a = win(kv(0, "x"), kv(1, "q", typ="afrl.cmasi.Other"))
        b = win(kv(0, "x"))
        self.assertTrue(C.get("canonical").compare(a, b))
        self.assertEqual(C.get("canonical", {"include": ["*KeyValuePair"]}).compare(a, b), [])
        self.assertEqual(C.get("canonical", {"exclude": ["*Other"]}).compare(a, b), [])

    def test_count_and_types(self):
        a = win(kv(0, "x"), kv(1, "y")); b = win(kv(0, "x"))
        self.assertEqual(len(C.get("count").compare(a, b)), 1)
        self.assertEqual(C.get("types").compare(a, b), [])

    def test_superset(self):
        a = win(kv(0, "x")); b = win(kv(0, "x"), kv(1, "extra"))
        self.assertEqual(C.get("superset").compare(a, b), [])
        self.assertEqual(len(C.get("superset").compare(b, a)), 1)

    def test_field_subset(self):
        m1 = kv(0, "x"); m1["obj"]["Other"] = 1
        m2 = kv(0, "x"); m2["obj"]["Other"] = 2
        self.assertEqual(C.get("field_subset", {"fields": ["Value"]}).compare(win(m1), win(m2)), [])
        with self.assertRaises(C.ComparatorError):
            C.get("field_subset").compare(win(m1), win(m2))

    def test_unknown_comparator(self):
        with self.assertRaises(C.ComparatorError):
            C.get("nope")

    def test_plugin_registration_and_use(self):
        @C.register("always_ok_test")
        class Ok(C.Comparator):
            def compare_windows(self, a, c):
                return []
        try:
            self.assertIn("always_ok_test", C.names())
            self.assertEqual(C.run_all([{"name": "always_ok_test"}], win(kv(0, "x")), win(kv(0, "y"))), [])
        finally:
            C.unregister("always_ok_test")

    def test_plugin_file_loading_and_diff_tagging(self):
        with tmpdir() as d:
            p = os.path.join(d, "plug.py")
            with open(p, "w") as fd:
                fd.write("from difftool import comparators as C, report as R\n"
                         "@C.register('plug_file_test')\n"
                         "class P(C.Comparator):\n"
                         "    def compare_windows(self, a, c):\n"
                         "        return [R.Difference(R.COUNT, 'boom')]\n")
            C.load_plugin(p)
            try:
                diffs = C.run_all([{"name": "plug_file_test"}], [], [])
                self.assertEqual(diffs[0].comparator, "plug_file_test")
            finally:
                C.unregister("plug_file_test")
        with self.assertRaises(C.ComparatorError):
            C.load_plugin("/nonexistent/x.py")

    def test_register_rejects_non_comparator(self):
        with self.assertRaises(TypeError):
            C.register("bad")(object)


class ReportTests(unittest.TestCase):
    def test_diff_values(self):
        got = list(R.diff_values({"a": 1, "b": [1, 2], "c": {"d": 1}},
                                 {"a": 2, "b": [1], "e": 0, "c": {"d": 1}}))
        paths = [g[0] for g in got]
        self.assertEqual(paths, ["a", "b[]", "e"])

    def test_render_match_and_diff(self):
        ok = R.Report("s", [], {"ada_messages": 2})
        self.assertTrue(ok.ok)
        self.assertIn("RESULT: MATCH", ok.render())
        bad = R.Report("s", [R.Difference(R.MISMATCH, "m", 0, "T", ada=1, cpp=2, path="p",
                                          comparator="canonical")])
        text = bad.render()
        self.assertIn("RESULT: DIFFERENT (1 difference)", text)
        self.assertIn("path: p", text)
        self.assertIn("ada: 1", text)

    def test_render_truncates(self):
        diffs = [R.Difference(R.COUNT, "d%d" % i) for i in range(5)]
        self.assertIn("3 more not shown", R.Report("s", diffs).render(max_diffs=2))

    def test_json_roundtrip(self):
        r = R.Report("s", [R.Difference(R.MISSING_IN_CPP, "m", 1, "T", ada={"x": 1})], notes=["n"])
        d = json.loads(r.to_json())
        self.assertFalse(d["ok"])
        self.assertEqual(d["differences"][0]["kind"], "missing_in_cpp")
        self.assertEqual(d["notes"], ["n"])


if __name__ == "__main__":
    unittest.main()
