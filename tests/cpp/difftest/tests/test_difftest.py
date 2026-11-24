"""Pure-python tests (no binaries, pyzmq or pylmcp needed).

Run: ``cd tests/cpp && python3 -m pytest -p no:cacheprovider difftest/tests``
(or ``python3 -m unittest discover -s difftest/tests -t .`` from tests/cpp).
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from difftest import EXIT_DIFF, EXIT_MATCH, EXIT_USAGE, cli, comparators, golden
from difftest.config import build_config
from difftest.normalise import normalise
from difftest.scenario import ScenarioError, load_scenario, parse_scenario

SCEN_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scenarios")


def rec(descriptor, obj, step=0, sid=1, t=1.0, eid=100):
    return {"descriptor": descriptor, "address": descriptor,
            "content_type": "lmcp", "source_group": "",
            "source_entity_id": eid, "source_service_id": sid,
            "obj": obj, "raw_hex": "", "step": step, "t": t}


class ScenarioTests(unittest.TestCase):
    def test_smoke_scenario_loads(self):
        sc = load_scenario(os.path.join(SCEN_DIR, "smoke_heartbeat.json"))
        self.assertEqual(sc.name, "smoke_heartbeat")
        self.assertEqual(len(sc.messages), 3)
        self.assertTrue(all(m.lmcp["type"] == "KeyValuePair" for m in sc.messages))
        self.assertFalse(any("AutomationRequest" in json.dumps(m.lmcp)
                             for m in sc.messages))

    def test_validation_errors(self):
        for bad in ({}, {"name": "x", "bogus": 1},
                    {"name": "x", "messages": [{"hex": "zz"}]},
                    {"name": "x", "messages": [{"hex": "00", "lmcp": {"type": "a"}}]},
                    {"name": "x", "services": [{"type": "S", "only": "java"}]},
                    {"name": "x", "settle": {"final_s": -1}},
                    {"name": "x", "comparators": [{}]}):
            with self.assertRaises(ScenarioError, msg=str(bad)):
                parse_scenario(bad)

    def test_invalid_json_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{nope")
        try:
            with self.assertRaises(ScenarioError):
                load_scenario(f.name)
        finally:
            os.unlink(f.name)

    def test_fingerprint_ignores_comparators(self):
        a = parse_scenario({"name": "x", "messages": [{"hex": "00"}]})
        b = parse_scenario({"name": "x", "messages": [{"hex": "00"}],
                            "comparators": [{"name": "types"}]})
        c = parse_scenario({"name": "x", "messages": [{"hex": "01"}]})
        self.assertEqual(a.fingerprint(), b.fingerprint())
        self.assertNotEqual(a.fingerprint(), c.fingerprint())

    def test_config_generation_equivalent(self):
        sc = parse_scenario({"name": "x", "entity_id": 7, "services": [
            {"type": "Both", "attributes": {"A": 1}},
            {"type": "AdaOnly", "only": "ada"},
            {"type": "CppOnly", "only": "cpp",
             "children": [{"tag": "Sub", "attributes": {"k": "v"}}]}]})
        ada = ET.fromstring(build_config(sc, "ada"))
        cpp = ET.fromstring(build_config(sc, "cpp"))
        self.assertEqual(ada.get("EntityID"), "7")
        self.assertEqual(ada.find("Bridge").attrib, cpp.find("Bridge").attrib)
        types = lambda r: [s.get("Type") for s in r.findall("Service")]
        self.assertEqual(types(ada), ["Both", "AdaOnly"])
        self.assertEqual(types(cpp), ["Both", "CppOnly"])
        self.assertEqual(cpp.find("Service/Sub").get("k"), "v")


class NormaliseTests(unittest.TestCase):
    def test_strips_times_and_service_ids(self):
        a = [rec("T", {"Key": "k", "Time": 5, "TimeStamp": 9}, sid=1, t=1)]
        b = [rec("T", {"Key": "k", "Time": 77}, sid=42, t=99)]
        self.assertEqual([m["key"] for m in normalise(a)],
                         [m["key"] for m in normalise(b)])

    def test_semantic_value_not_stripped(self):
        a = normalise([rec("T", {"Key": "k", "Value": "1"})])
        b = normalise([rec("T", {"Key": "k", "Value": "2"})])
        self.assertNotEqual(a[0]["key"], b[0]["key"])

    def test_ordering_within_window_only(self):
        x, y = rec("A", {"v": 1}), rec("B", {"v": 2})
        n1 = normalise([x, y])
        n2 = normalise([y, x])
        self.assertEqual([m["key"] for m in n1], [m["key"] for m in n2])
        # different windows keep their order
        w = normalise([rec("B", {}, step=0), rec("A", {}, step=1)])
        self.assertEqual([m["type"] for m in w], ["B", "A"])
        # window=all merges
        w = normalise([rec("B", {}, step=0), rec("A", {}, step=1)],
                      {"window": "all"})
        self.assertEqual([m["type"] for m in w], ["A", "B"])

    def test_id_renumbering_preserves_linkage(self):
        a = normalise([rec("R", {"RequestID": 1000, "Ref": {"RequestID": 1000}}),
                       rec("S", {"RequestID": 1000})])
        b = normalise([rec("R", {"RequestID": 5, "Ref": {"RequestID": 5}}),
                       rec("S", {"RequestID": 5})])
        self.assertEqual([m["key"] for m in a], [m["key"] for m in b])
        # but broken linkage is detected
        c = normalise([rec("R", {"RequestID": 5, "Ref": {"RequestID": 6}}),
                       rec("S", {"RequestID": 5})])
        self.assertNotEqual([m["key"] for m in a], [m["key"] for m in c])

    def test_id_modes(self):
        r = [rec("R", {"RequestID": 3})]
        self.assertEqual(normalise(r, {"id_mode": "strip"})[0]["msg"]["body"],
                         {"RequestID": "<id>"})
        self.assertEqual(normalise(r, {"id_mode": "keep"})[0]["msg"]["body"],
                         {"RequestID": 3})

    def test_ignore_types_and_keys_and_floats(self):
        r = [rec("a.Noise", {}), rec("b.Real", {"x": 1.00000001, "junk": 1})]
        n = normalise(r, {"ignore_types": ["*.Noise"], "ignore_keys": ["^junk$"]})
        self.assertEqual(len(n), 1)
        self.assertEqual(n[0]["msg"]["body"], {"x": 1.0})

    def test_undecoded_falls_back_to_payload(self):
        r = rec("T", None)
        r["raw_hex"] = b"T$lmcp|T||1|2$\x01\x02".hex()
        self.assertEqual(normalise([r])[0]["msg"]["body"],
                         {"_undecoded_payload": "0102"})


class ComparatorTests(unittest.TestCase):
    def n(self, *recs):
        return normalise(list(recs))

    def test_canonical_match_and_diff(self):
        a = self.n(rec("T", {"Key": "a"}), rec("U", {"Key": "b"}))
        b = self.n(rec("U", {"Key": "b"}), rec("T", {"Key": "a"}))
        self.assertEqual(comparators.canonical(a, b, {}), [])
        c = self.n(rec("T", {"Key": "z"}), rec("V", {}))
        kinds = sorted(d.kind for d in comparators.canonical(a, c, {}))
        self.assertEqual(kinds, ["mismatch", "missing", "unexpected"])
        mm = [d for d in comparators.canonical(a, c, {}) if d.kind == "mismatch"][0]
        self.assertIn("Key", mm.detail)

    def test_types_subset_ignore(self):
        a = self.n(rec("T", {"v": 1}))
        b = self.n(rec("T", {"v": 2}), rec("X", {}))
        self.assertEqual(comparators.types_only(a, b, {})[0].kind, "count")
        self.assertEqual(comparators.subset(a, b, {})[0].kind, "mismatch")
        self.assertEqual(comparators.ignore(a, b, {}), [])

    def test_registry_plugin_and_dispatch(self):
        @comparators.register("always_fail_test")
        def always_fail(ref, cand, options):
            return [comparators.Difference("mismatch", 0, "x", "boom")]
        a = self.n(rec("svc.A", {}), rec("other.B", {"v": 1}))
        b = self.n(rec("svc.A", {}), rec("other.B", {"v": 1}))
        res = comparators.compare_all(a, b, [
            {"name": "always_fail_test", "service": "svc", "match": ["svc.*"]}])
        by = {r.service: r for r in res}
        self.assertEqual(len(by["svc"].differences), 1)
        self.assertEqual(by["<default>"].differences, [])
        self.assertEqual(by["<default>"].ref_count, 1)

    def test_unknown_comparator(self):
        with self.assertRaises(comparators.UnknownComparator):
            comparators.get("nope")


class GoldenAndCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sc = parse_scenario({"name": "g", "messages": [{"hex": "00"}]})

    def test_golden_roundtrip_and_stale(self):
        p = golden.golden_path(self.tmp.name, "g")
        recs = [rec("T", {"a": 1})]
        golden.save(p, self.sc, "ada", recs)
        self.assertEqual(golden.load(p, self.sc), recs)
        other = parse_scenario({"name": "g", "messages": [{"hex": "01"}]})
        with self.assertRaises(golden.GoldenError):
            golden.load(p, other)
        self.assertEqual(golden.load(p, other, allow_stale=True), recs)
        with self.assertRaises(golden.GoldenError):
            golden.load(os.path.join(self.tmp.name, "missing.json"), self.sc)

    def test_compare_and_report_exit_codes(self):
        ref = [rec("T", {"a": 1}, sid=1)]
        out = os.path.join(self.tmp.name, "r.json")
        self.assertEqual(cli.compare_and_report(
            self.sc, ref, [rec("T", {"a": 1}, sid=9)], out), EXIT_MATCH)
        self.assertTrue(json.load(open(out))["match"])
        self.assertEqual(cli.compare_and_report(
            self.sc, ref, [rec("T", {"a": 2})], out), EXIT_DIFF)
        self.assertFalse(json.load(open(out))["match"])

    def test_cli_no_binaries_paths(self):
        smoke = os.path.join(SCEN_DIR, "smoke_heartbeat.json")
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            self._cli_checks(smoke)

    def _cli_checks(self, smoke):
        self.assertEqual(cli.main(["--validate", smoke]), EXIT_MATCH)
        self.assertEqual(cli.main(["--dump-config", "cpp", smoke]), EXIT_MATCH)
        self.assertEqual(cli.main(["--list-comparators"]), EXIT_MATCH)
        self.assertEqual(cli.main([]), EXIT_USAGE)
        self.assertEqual(cli.main([os.path.join(self.tmp.name, "no.json")]),
                         EXIT_USAGE)

    def test_use_golden_missing_is_infra_error(self):
        smoke = os.path.join(SCEN_DIR, "smoke_heartbeat.json")
        rc = cli.main(["--use-golden", "--golden-dir", self.tmp.name, smoke])
        self.assertEqual(rc, 3)


if __name__ == "__main__":
    unittest.main()
