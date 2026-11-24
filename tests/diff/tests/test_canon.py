import unittest

import _path  # noqa: F401
from uxas_diff.canon import canonicalise, make_config


def rec(desc, obj, phase=0, t=0, **kw):
    r = {"descriptor": desc, "address": desc, "obj": obj, "phase": phase,
         "t_ms": t, "source_entity_id": 1, "source_service_id": 2}
    r.update(kw)
    return r


class CanonTest(unittest.TestCase):
    def test_strips_volatile_fields_nested(self):
        a = canonicalise([rec("T", {"ID": 1, "Time": 5,
                                    "Sub": {"Time": 9, "X": 1}})])
        b = canonicalise([rec("T", {"ID": 1, "Time": 77,
                                    "Sub": {"Time": 1, "X": 1}})])
        self.assertEqual(a, b)
        self.assertNotIn("Time", a[0]["obj"])
        self.assertNotIn("Time", a[0]["obj"]["Sub"])

    def test_source_metadata_ignored(self):
        a = canonicalise([rec("T", {"A": 1}, source_service_id=1, t=10)])
        b = canonicalise([rec("T", {"A": 1}, source_service_id=9, t=99)])
        self.assertEqual(a, b)

    def test_sorted_within_window_order_independent(self):
        x, y, z = rec("B", {"A": 1}), rec("A", {"A": 2}), rec("A", {"A": 1})
        self.assertEqual(canonicalise([x, y, z]), canonicalise([z, x, y]))
        types = [m["type"] for m in canonicalise([x, y, z])]
        self.assertEqual(types, ["A", "A", "B"])

    def test_renumber_ids_consistent_and_value_independent(self):
        m1 = [rec("Req", {"RequestID": 1001, "N": 1}),
              rec("Resp", {"RequestID": 1001, "N": 2})]
        m2 = [rec("Resp", {"RequestID": 7, "N": 2}),
              rec("Req", {"RequestID": 7, "N": 1})]
        c1, c2 = canonicalise(m1), canonicalise(m2)
        self.assertEqual(c1, c2)
        ids = {m["obj"]["RequestID"] for m in c1}
        self.assertEqual(len(ids), 1)  # cross reference preserved
        self.assertTrue(ids.pop().startswith("<id:"))

    def test_renumber_distinguishes_different_ids(self):
        c = canonicalise([rec("Req", {"RequestID": 1, "N": 1}),
                          rec("Req", {"RequestID": 2, "N": 2})])
        self.assertEqual(len({m["obj"]["RequestID"] for m in c}), 2)

    def test_float_rounding(self):
        a = canonicalise([rec("T", {"F": 1.0000001})])
        b = canonicalise([rec("T", {"F": 1.0000002})])
        c = canonicalise([rec("T", {"F": 1.01})])
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_drop_empty(self):
        a = canonicalise([rec("T", {"A": 1, "L": [], "S": "", "N": None})])
        self.assertEqual(a[0]["obj"], {"A": 1})
        b = canonicalise([rec("T", {"A": 1, "L": []})],
                         {"drop_empty": False})
        self.assertIn("L", b[0]["obj"])

    def test_zero_not_dropped(self):
        self.assertEqual(canonicalise([rec("T", {"A": 0})])[0]["obj"],
                         {"A": 0})

    def test_window_phase_and_all_and_time(self):
        recs = [rec("T", {"A": 1}, phase=0, t=10),
                rec("T", {"A": 1}, phase=2, t=1500)]
        self.assertEqual([m["window"] for m in
                          canonicalise(recs, {"window": "phase"})], [0, 2])
        self.assertEqual({m["window"] for m in
                          canonicalise(recs, {"window": "all"})}, {0})
        self.assertEqual([m["window"] for m in
                          canonicalise(recs, {"window": 1000})], [0, 1])

    def test_window_difference_is_visible(self):
        a = canonicalise([rec("T", {"A": 1}, phase=1)])
        b = canonicalise([rec("T", {"A": 1}, phase=2)])
        self.assertNotEqual(a, b)

    def test_type_filters(self):
        recs = [rec("afrl.A", {}), rec("uxas.B", {"x": 1})]
        self.assertEqual(len(canonicalise(recs, {"ignore_types": ["uxas.*"]})), 1)
        c = canonicalise(recs, {"only_types": ["uxas.*"]})
        self.assertEqual([m["type"] for m in c], ["uxas.B"])

    def test_unknown_option_rejected(self):
        with self.assertRaises(ValueError):
            make_config({"bogus": 1})

    def test_input_not_mutated(self):
        r = rec("T", {"Time": 1, "L": []})
        canonicalise([r])
        self.assertIn("Time", r["obj"])


if __name__ == "__main__":
    unittest.main()
