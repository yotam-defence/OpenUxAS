import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import _path  # noqa: F401
from uxas_diff import cli

SC = {"name": "s", "messages": [], "capture": {}}


def rec(v):
    return {"address": "a", "descriptor": "d", "content_type": "c",
            "source_group": "", "source_entity_id": 1,
            "source_service_id": 0, "obj": {"v": v}, "phase": 0, "t_ms": 0}


class CliBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gdir = os.path.join(self.tmp.name, "golden")
        os.makedirs(self.gdir)
        self.calls = []
        self.results = {"ada": [rec(1)], "cpp": [rec(1)]}

        def run_impl(sc, impl, binary, hub_bin=None, keep_dir=None):
            self.calls.append((impl, binary, hub_bin))
            return self.results[impl]

        for p in (mock.patch.object(cli.scen, "load", return_value=dict(SC)),
                  mock.patch.object(cli.runner, "find_binary",
                                    side_effect=lambda k, o: "/bin/" + k),
                  mock.patch.object(cli.runner, "run_impl", run_impl)):
            p.start()
            self.addCleanup(p.stop)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def write_golden(self, msgs, provenance=None):
        doc = {"scenario": "s", "messages": msgs}
        if provenance:
            doc["provenance"] = provenance
        with open(os.path.join(self.gdir, "s.json"), "w") as fd:
            json.dump(doc, fd)


class CliRunTest(CliBase):
    def test_run_golden_ok_runs_only_cpp(self):
        self.write_golden([rec(1)])
        rc, _, _ = self.main("run", "s", "--golden", "--golden-dir",
                             self.gdir)
        self.assertEqual(rc, cli.EXIT_OK)
        self.assertEqual([c[0] for c in self.calls], ["cpp"])

    def test_run_golden_mismatch(self):
        self.write_golden([rec(2)])
        rc, _, _ = self.main("run", "s", "--golden", "--golden-dir",
                             self.gdir)
        self.assertEqual(rc, cli.EXIT_MISMATCH)

    def test_run_golden_synthetic_warns(self):
        self.write_golden([rec(1)], provenance="synthetic")
        _, _, err = self.main("run", "s", "--golden", "--golden-dir",
                              self.gdir)
        self.assertIn("synthetic", err)

    def test_run_without_golden_runs_ada_then_cpp(self):
        rc, _, _ = self.main("run", "s")
        self.assertEqual(rc, cli.EXIT_OK)
        self.assertEqual(self.calls, [("ada", "/bin/ada", "/bin/cpp"),
                                      ("cpp", "/bin/cpp", None)])

    def test_save_captures_and_report(self):
        caps = os.path.join(self.tmp.name, "caps")
        report = os.path.join(self.tmp.name, "r.json")
        self.main("run", "s", "--save-captures", caps, "--report", report)
        self.assertTrue(os.path.isfile(os.path.join(caps, "s.ref.json")))
        self.assertTrue(os.path.isfile(os.path.join(caps, "s.cpp.json")))
        self.assertTrue(os.path.isfile(report))

    def test_run_error_maps_to_exit_error(self):
        with mock.patch.object(cli.runner, "run_impl",
                               side_effect=cli.runner.RunnerError("boom")):
            rc, _, err = self.main("run", "s")
        self.assertEqual(rc, cli.EXIT_ERROR)
        self.assertIn("boom", err)


class CliRecordTest(CliBase):
    def test_record_ada(self):
        rc, out, _ = self.main("record", "s", "--golden-dir", self.gdir)
        self.assertEqual(rc, cli.EXIT_OK)
        self.assertEqual(self.calls, [("ada", "/bin/ada", "/bin/cpp")])
        self.assertIn("recorded 1 messages", out)
        self.assertTrue(os.path.isfile(os.path.join(self.gdir, "s.json")))

    def test_record_cpp_has_no_hub(self):
        self.main("record", "s", "--impl", "cpp", "--golden-dir", self.gdir)
        self.assertEqual(self.calls, [("cpp", "/bin/cpp", None)])


if __name__ == "__main__":
    unittest.main()
