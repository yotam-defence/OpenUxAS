import json
import os
import subprocess
import sys
import tempfile
import unittest

import _path  # noqa: F401
from uxas_diff import comparators, golden
from uxas_diff.canon import canonicalise
from uxas_diff.cli import main
from uxas_diff.diffing import diff_records, select_comparator


def cm(type_, obj, window=0):
    return {"window": window, "type": type_, "obj": obj}


def rec(desc, obj, phase=0):
    return {"descriptor": desc, "obj": obj, "phase": phase, "t_ms": 0}


class RegistryTest(unittest.TestCase):
    def tearDown(self):
        comparators.unregister("t_custom")

    def test_builtins_registered(self):
        for n in ("canonical", "count", "ignore"):
            self.assertIn(n, comparators.names())

    def test_register_and_duplicate(self):
        comparators.register("t_custom", lambda r, t, c: [])
        with self.assertRaises(ValueError):
            comparators.register("t_custom", lambda r, t, c: [])
        comparators.register("t_custom", lambda r, t, c: ["x"], replace=True)
        self.assertEqual(comparators.get("t_custom")([], [], {}), ["x"])

    def test_decorator(self):
        @comparators.comparator("t_custom")
        def f(ref, test, ctx):
            return []
        self.assertIs(comparators.get("t_custom"), f)

    def test_unknown(self):
        with self.assertRaises(comparators.UnknownComparator):
            comparators.get("nope")

    def test_load_plugin_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "plug.py")
            with open(p, "w") as fd:
                fd.write("from uxas_diff.comparators import comparator\n"
                         "@comparator('t_custom')\n"
                         "def f(r, t, c):\n    return []\n")
            comparators.load_plugin(p)
        self.assertIn("t_custom", comparators.names())

    def test_builtin_canonical(self):
        a = [cm("T", {"x": 1}), cm("T", {"x": 2})]
        self.assertEqual(comparators.get("canonical")(a, list(reversed(a)), {}), [])
        out = comparators.get("canonical")(a, [a[0]], {})
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("missing in test"))
        out = comparators.get("canonical")([a[0]], a, {})
        self.assertTrue(out[0].startswith("unexpected in test"))

    def test_count_and_ignore(self):
        a = [cm("T", {"x": 1})]
        b = [cm("T", {"x": 2})]
        self.assertEqual(comparators.get("count")(a, b, {}), [])
        self.assertTrue(comparators.get("count")(a, a + b, {}))
        self.assertEqual(comparators.get("ignore")(a, [], {}), [])


class DiffTest(unittest.TestCase):
    def tearDown(self):
        comparators.unregister("t_custom")

    def test_select_exact_glob_default(self):
        m = {"afrl.*": "count", "afrl.cmasi.X": "ignore"}
        self.assertEqual(select_comparator("afrl.cmasi.X", m), "ignore")
        self.assertEqual(select_comparator("afrl.cmasi.Y", m), "count")
        self.assertEqual(select_comparator("uxas.Z", m), "canonical")

    def test_match(self):
        r = diff_records([rec("T", {"a": 1, "Time": 1})],
                         [rec("T", {"a": 1, "Time": 2})])
        self.assertTrue(r.ok)
        self.assertIn("MATCH", r.text())

    def test_mismatch_value_missing_extra_type(self):
        r = diff_records([rec("T", {"a": 1}), rec("U", {})],
                         [rec("T", {"a": 2}), rec("V", {})])
        self.assertFalse(r.ok)
        self.assertEqual({m.type for m in r.mismatches}, {"T", "U", "V"})
        self.assertIn("MISMATCH", r.text())
        self.assertFalse(r.as_dict()["ok"])

    def test_per_type_comparator_plugin(self):
        comparators.register(
            "t_custom",
            lambda ref, test, ctx: [] if len(ref) == len(test) else ["n"])
        sc = {"comparators": {"T": "t_custom"}}
        ok = diff_records([rec("T", {"a": 1})], [rec("T", {"a": 99})], sc)
        self.assertTrue(ok.ok)
        bad = diff_records([rec("T", {"a": 1})], [], sc)
        self.assertFalse(bad.ok)
        self.assertEqual(bad.mismatches[0].comparator, "t_custom")

    def test_ignore_type_via_canon_config(self):
        sc = {"canon": {"ignore_types": ["U"]}}
        r = diff_records([rec("T", {}), rec("U", {"a": 1})], [rec("T", {})], sc)
        self.assertTrue(r.ok)

    def test_window_mismatch(self):
        sc = {"canon": {"window": "phase"}}
        r = diff_records([rec("T", {}, 1)], [rec("T", {}, 2)], sc)
        self.assertFalse(r.ok)
        r = diff_records([rec("T", {}, 1)], [rec("T", {}, 2)],
                         {"canon": {"window": "all"}})
        self.assertTrue(r.ok)


class CliOfflineTest(unittest.TestCase):
    def _write(self, d, name, recs):
        p = os.path.join(d, name)
        with open(p, "w") as fd:
            json.dump({"messages": recs}, fd)
        return p

    def test_diff_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            a = self._write(d, "a.json", [rec("T", {"a": 1})])
            b = self._write(d, "b.json", [rec("T", {"a": 1, "Time": 3})])
            c = self._write(d, "c.json", [rec("T", {"a": 2})])
            self.assertEqual(main(["diff", a, b]), 0)
            self.assertEqual(main(["diff", a, c]), 1)
            self.assertEqual(main(["diff", a, os.path.join(d, "none")]), 2)

    def test_python_dash_m_exit_status(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as d:
            a = self._write(d, "a.json", [rec("T", {"a": 1})])
            c = self._write(d, "c.json", [rec("T", {"a": 2})])
            p = subprocess.run([sys.executable, "-m", "uxas_diff", "diff", a, c],
                               cwd=root, capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertIn("MISMATCH", p.stdout)

    def test_canon_output(self):
        with tempfile.TemporaryDirectory() as d:
            a = self._write(d, "a.json", [rec("T", {"a": 1, "Time": 3})])
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(main(["canon", a]), 0)
            self.assertEqual(json.loads(buf.getvalue()),
                             canonicalise([rec("T", {"a": 1})]))

    def test_golden_missing_is_error(self):
        with self.assertRaises(golden.GoldenError):
            golden.load("no_such_scenario", golden_dir=tempfile.gettempdir())

    def test_golden_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            golden.save("s", [rec("T", {"a": 1})], golden_dir=d)
            doc = golden.load("s", golden_dir=d)
            self.assertEqual(doc["messages"], [rec("T", {"a": 1})])
            self.assertEqual(doc["impl"], "ada")


class SmokeGoldenTest(unittest.TestCase):
    """The shipped smoke golden must be self-consistent (no binaries)."""

    def test_smoke_golden_matches_itself_and_detects_tamper(self):
        from uxas_diff import scenario
        sc = scenario.load("smoke_heartbeat")
        doc = golden.load("smoke_heartbeat")
        msgs = doc["messages"]
        self.assertTrue(msgs)
        self.assertTrue(diff_records(msgs, msgs, sc, sc["name"]).ok)
        tampered = json.loads(json.dumps(msgs))
        tampered[-1]["obj"]["Heading"] += 10
        self.assertFalse(diff_records(msgs, tampered, sc, sc["name"]).ok)
        self.assertFalse(diff_records(msgs, msgs[:-1], sc, sc["name"]).ok)


if __name__ == "__main__":
    unittest.main()
