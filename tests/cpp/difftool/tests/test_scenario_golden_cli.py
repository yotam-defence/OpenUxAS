import io
import json
import os
import unittest

from difftool import EXIT_DIFF, EXIT_GOLDEN, EXIT_INFRA, EXIT_MATCH, EXIT_USAGE
from difftool import cli, golden, runner, scenario
from .helpers import (SCEN_DIR, FakeLauncher, FakeTransport, kv, tmpdir,
                      write_scenario)


class ScenarioTests(unittest.TestCase):
    def test_parse_defaults(self):
        with tmpdir() as d:
            s = scenario.load(write_scenario(d))
            self.assertEqual(s.name, "t")
            self.assertEqual(len(s.messages), 2)
            self.assertEqual(s.messages[0].delay_ms, 5)
            self.assertEqual(s.comparators, [{"name": "canonical"}])
            self.assertEqual(s.capture, [""])
            self.assertEqual(s.endpoint["pub"], "tcp://127.0.0.1:5560")
            self.assertTrue(os.path.isabs(s.ada_cfg))

    def test_missing_required(self):
        with tmpdir() as d:
            write_scenario(d)
            with self.assertRaises(scenario.ScenarioError):
                scenario.parse({"name": "x"}, d)

    def test_unknown_key_and_bad_types(self):
        with tmpdir() as d:
            p = write_scenario(d, bogus=1)
            with self.assertRaises(scenario.ScenarioError):
                scenario.load(p)
            p = write_scenario(d, settle_ms=-1)
            with self.assertRaises(scenario.ScenarioError):
                scenario.load(p)
            p = write_scenario(d, messages=[{"fields": {}}])
            with self.assertRaises(scenario.ScenarioError):
                scenario.load(p)
            p = write_scenario(d, normalization={"id_mode": "x"})
            with self.assertRaises(scenario.ScenarioError):
                scenario.load(p)

    def test_missing_cfg_file_and_bad_json(self):
        with tmpdir() as d:
            p = write_scenario(d, ada_cfg="nope.xml")
            with self.assertRaises(scenario.ScenarioError):
                scenario.load(p)
            with open(p, "w") as fd:
                fd.write("{not json")
            with self.assertRaises(scenario.ScenarioError):
                scenario.load(p)

    def test_comparator_string_shorthand(self):
        with tmpdir() as d:
            s = scenario.load(write_scenario(d, comparators=["count"]))
            self.assertEqual(s.comparators, [{"name": "count"}])

    def test_fingerprint_ignores_cpp_cfg_but_not_messages(self):
        with tmpdir() as d:
            s1 = scenario.load(write_scenario(d))
            with open(os.path.join(d, "c.xml"), "w") as fd:
                fd.write("<changed/>")
            self.assertEqual(s1.reference_fingerprint(), scenario.load(os.path.join(d, "s.json")).reference_fingerprint())
            s2 = scenario.load(write_scenario(d, settle_ms=5))
            self.assertNotEqual(s1.reference_fingerprint(), s2.reference_fingerprint())

    def test_shipped_smoke_scenario_parses(self):
        s = scenario.load(os.path.join(SCEN_DIR, "heartbeat_smoke.json"))
        self.assertTrue(s.messages)
        self.assertTrue(all(m.cls == "KeyValuePair" for m in s.messages))
        self.assertTrue(os.path.isfile(s.ada_cfg) and os.path.isfile(s.cpp_cfg))


class GoldenTests(unittest.TestCase):
    def test_roundtrip(self):
        with tmpdir() as d:
            golden.save(d, "a/b c", "fp", [kv(0, "x")])
            self.assertEqual(golden.load(d, "a/b c", "fp"), [kv(0, "x")])

    def test_missing(self):
        with tmpdir() as d:
            with self.assertRaises(golden.GoldenMissing):
                golden.load(d, "x")

    def test_stale_and_allow_stale(self):
        with tmpdir() as d:
            golden.save(d, "x", "old", [])
            with self.assertRaises(golden.GoldenStale):
                golden.load(d, "x", "new")
            self.assertEqual(golden.load(d, "x", "new", allow_stale=True), [])

    def test_corrupt(self):
        with tmpdir() as d:
            with open(golden.golden_path(d, "x"), "w") as fd:
                fd.write("{")
            with self.assertRaises(golden.GoldenError):
                golden.load(d, "x")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        FakeTransport.instances = []
        self.nosleep = lambda s: None

    def test_run_side_ada_starts_hub_and_stops_everything(self):
        with tmpdir() as d:
            s = scenario.load(write_scenario(d, ada_hub_cfg="h.xml"))
            L = FakeLauncher()
            raw = runner.run_side(s, "ada", "/ada", L, FakeTransport, self.nosleep, "/cpp")
            self.assertEqual([p.name for p in L.procs], ["ada_hub", "ada"])
            self.assertEqual(L.procs[0].argv[:2], ["/cpp", "-cfgPath"])
            self.assertEqual(L.procs[1].argv[0], "/ada")
            self.assertTrue(all(p.stopped for p in L.procs))
            self.assertEqual(len(raw), 2)
            self.assertTrue(FakeTransport.instances[0].closed)

    def test_hub_requires_cpp_bin(self):
        with tmpdir() as d:
            s = scenario.load(write_scenario(d, ada_hub_cfg="h.xml"))
            with self.assertRaises(runner.RunError):
                runner.run_side(s, "ada", "/ada", FakeLauncher(), FakeTransport, self.nosleep)

    def test_premature_exit_is_error_and_cleans_up(self):
        with tmpdir() as d:
            s = scenario.load(write_scenario(d))
            L = FakeLauncher(die={"cpp"})
            with self.assertRaises(runner.RunError):
                runner.run_side(s, "cpp", "/cpp", L, FakeTransport, self.nosleep)
            self.assertTrue(L.procs[0].stopped)

    def test_obtain_ada_records_then_reuses_golden(self):
        with tmpdir() as d, tmpdir() as g:
            s = scenario.load(write_scenario(d))
            L = FakeLauncher()
            raw, notes = runner.obtain_ada(s, "/ada", None, g, False, False, L, FakeTransport, self.nosleep)
            self.assertTrue(any("recorded" in n for n in notes))
            n_procs = len(L.procs)
            raw2, notes2 = runner.obtain_ada(s, None, None, g, False, False, L, FakeTransport, self.nosleep)
            self.assertEqual(raw, raw2)
            self.assertEqual(len(L.procs), n_procs)  # no new process
            self.assertTrue(any("golden file" in n for n in notes2))

    def test_provisional_golden_is_flagged_and_usable(self):
        with tmpdir() as d, tmpdir() as g:
            s = scenario.load(write_scenario(d))
            L = FakeLauncher()
            path = runner.record_provisional(s, "/cpp", g, L, FakeTransport, self.nosleep)
            doc = json.load(open(path))
            self.assertTrue(doc["provisional"])
            self.assertEqual(doc["recorded_from"], "cpp")
            self.assertIn("PROVISIONAL", doc["note"])
            raw, notes = runner.obtain_ada(s, None, None, g, False, False, L, FakeTransport, self.nosleep)
            self.assertTrue(any("PROVISIONAL" in n for n in notes))

    def test_real_golden_is_not_provisional(self):
        with tmpdir() as g:
            path = golden.save(g, "x", "fp", [])
            doc = json.load(open(path))
            self.assertFalse(doc["provisional"])
            self.assertEqual(doc["recorded_from"], "ada")
            self.assertNotIn("note", doc)

    def test_obtain_ada_without_anything(self):
        with tmpdir() as d:
            s = scenario.load(write_scenario(d))
            with self.assertRaises(runner.RunError):
                runner.obtain_ada(s, None, None, None, False, False, FakeLauncher(), FakeTransport)


class CliTests(unittest.TestCase):
    def run_cli(self, argv, **kw):
        out = io.StringIO()
        rc = cli.main(argv, out=out, **kw)
        return rc, out.getvalue()

    def setUp(self):
        FakeTransport.instances = []

    def test_end_to_end_match_with_fakes(self):
        with tmpdir() as d, tmpdir() as g:
            rc, out = self.run_cli(["--scenario", write_scenario(d), "--ada-bin", "/a",
                                    "--cpp-bin", "/c", "--golden", g],
                                   launcher=FakeLauncher(), transport_factory=FakeTransport)
            self.assertEqual(rc, EXIT_MATCH, out)
            self.assertIn("RESULT: MATCH", out)
            # second run: golden only, still match
            rc, out = self.run_cli(["--scenario", os.path.join(d, "s.json"), "--cpp-bin", "/c",
                                    "--golden", g],
                                   launcher=FakeLauncher(), transport_factory=FakeTransport)
            self.assertEqual(rc, EXIT_MATCH, out)

    def test_diff_exit_code_and_report_file(self):
        with tmpdir() as d:
            p = write_scenario(d)
            a = os.path.join(d, "a.json"); c = os.path.join(d, "c.json"); rep = os.path.join(d, "r.json")
            json.dump({"messages": [kv(0, "x")]}, open(a, "w"))
            json.dump({"messages": [kv(0, "y")]}, open(c, "w"))
            rc, out = self.run_cli(["--scenario", p, "--compare-files", a, c, "--report", rep])
            self.assertEqual(rc, EXIT_DIFF)
            self.assertFalse(json.load(open(rep))["ok"])

    def test_golden_missing_exit_code(self):
        with tmpdir() as d, tmpdir() as g:
            rc, _ = self.run_cli(["--scenario", write_scenario(d), "--cpp-bin", "/c", "--golden", g],
                                 launcher=FakeLauncher(), transport_factory=FakeTransport)
            self.assertEqual(rc, EXIT_GOLDEN)

    def test_usage_errors(self):
        self.assertEqual(self.run_cli([])[0], EXIT_USAGE)
        self.assertEqual(self.run_cli(["--scenario", "/nonexistent.json"])[0], EXIT_USAGE)
        with tmpdir() as d:
            rc, _ = self.run_cli(["--scenario", write_scenario(d, comparators=["nope"]),
                                  "--ada-bin", "/a", "--cpp-bin", "/c"],
                                 launcher=FakeLauncher(), transport_factory=FakeTransport)
            self.assertEqual(rc, EXIT_USAGE)

    def test_infra_error_when_binary_dies(self):
        with tmpdir() as d:
            rc, _ = self.run_cli(["--scenario", write_scenario(d), "--ada-bin", "/a", "--cpp-bin", "/c"],
                                 launcher=FakeLauncher(die={"ada"}), transport_factory=FakeTransport)
            self.assertEqual(rc, EXIT_INFRA)

    def test_list_comparators(self):
        rc, out = self.run_cli(["--list-comparators"])
        self.assertEqual(rc, EXIT_MATCH)
        self.assertIn("canonical", out.split())


if __name__ == "__main__":
    unittest.main()
