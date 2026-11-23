import unittest

from difftool import normalize as n
from .helpers import kv


class NormalizeTests(unittest.TestCase):
    def test_timestamps_stripped(self):
        m = kv(0, "x")
        m["obj"]["Time"] = 12345
        m["obj"]["TimeStamp"] = 1
        m["obj"]["Nested"] = {"CreationTime": 5, "keep": 1}
        c = n.canonicalise([m])[0][0]
        self.assertNotIn("Time", c.body)
        self.assertNotIn("TimeStamp", c.body)
        self.assertEqual(c.body["Nested"], {"keep": 1})

    def test_service_id_ignored_but_entity_kept(self):
        a = n.canonicalise([kv(0, "x", service=3)])[0][0]
        b = n.canonicalise([kv(0, "x", service=9)])[0][0]
        self.assertEqual(a, b)
        c = n.canonicalise([kv(0, "x", entity=7)])[0][0]
        self.assertNotEqual(a, c)

    def test_ids_renumbered_consistently(self):
        a = n.canonicalise([kv(0, "x", req=900), kv(1, "y", req=901), kv(2, "z", req=900)])
        b = n.canonicalise([kv(0, "x", req=5), kv(1, "y", req=6), kv(2, "z", req=5)])
        self.assertEqual(a, b)
        self.assertEqual(a[0][0].body["RequestID"], "<id:1>")

    def test_id_renumber_detects_broken_correlation(self):
        a = n.canonicalise([kv(0, "x", req=1), kv(500, "y", req=1)], n.Options(window_ms=10))
        b = n.canonicalise([kv(0, "x", req=1), kv(500, "y", req=2)], n.Options(window_ms=10))
        self.assertNotEqual(a, b)

    def test_id_renumber_independent_of_arrival_order_in_window(self):
        a = n.canonicalise([kv(0, "x", req=10), kv(1, "y", req=11)])
        b = n.canonicalise([kv(0, "y", req=77), kv(1, "x", req=66)])
        # x has the "first" sort position in both -> same placeholder
        self.assertEqual(a, b)

    def test_id_mode_strip_and_keep(self):
        s = n.canonicalise([kv(0, "x", req=5)], n.Options(id_mode="strip"))[0][0]
        self.assertNotIn("RequestID", s.body)
        k = n.canonicalise([kv(0, "x", req=5)], n.Options(id_mode="keep"))[0][0]
        self.assertEqual(k.body["RequestID"], 5)

    def test_zero_id_kept(self):
        c = n.canonicalise([kv(0, "x", req=0)])[0][0]
        self.assertEqual(c.body["RequestID"], 0)

    def test_float_rounding_and_negative_zero(self):
        m1 = kv(0, "x"); m1["obj"]["Lat"] = 1.00000001; m1["obj"]["Z"] = -0.0
        m2 = kv(0, "x"); m2["obj"]["Lat"] = 1.0; m2["obj"]["Z"] = 0.0
        self.assertEqual(n.canonicalise([m1]), n.canonicalise([m2]))

    def test_float_digits_none_is_exact(self):
        m1 = kv(0, "x"); m1["obj"]["Lat"] = 1.0000001
        m2 = kv(0, "x"); m2["obj"]["Lat"] = 1.0
        o = n.Options(float_digits=None)
        self.assertNotEqual(n.canonicalise([m1], o), n.canonicalise([m2], o))

    def test_bad_options(self):
        with self.assertRaises(ValueError):
            n.Options.from_dict({"id_mode": "bogus"})
        with self.assertRaises(ValueError):
            n.Options.from_dict({"nope": 1})
        with self.assertRaises(ValueError):
            n.Options.from_dict({"strip_fields": ["("]})


class WindowTests(unittest.TestCase):
    def test_gap_windows(self):
        ws = n.canonicalise([kv(0, "a"), kv(100, "b"), kv(1000, "c")], n.Options(window_ms=200))
        self.assertEqual([len(w) for w in ws], [2, 1])

    def test_sorted_by_type_within_window(self):
        a = kv(0, "x"); b = kv(5, "x", typ="afrl.cmasi.AAA")
        ws1 = n.canonicalise([a, b]); ws2 = n.canonicalise([b, dict(a, t_ms=6)])
        self.assertEqual(ws1[0][0].type, "afrl.cmasi.AAA")
        self.assertEqual(ws1, ws2)

    def test_windows_across_boundary_not_reordered(self):
        a = kv(0, "x"); b = kv(1000, "y", typ="afrl.cmasi.AAA")
        ws = n.canonicalise([b, a], n.Options(window_ms=100))
        self.assertEqual([w[0].type for w in ws], ["afrl.cmasi.KeyValuePair", "afrl.cmasi.AAA"])

    def test_window_zero_is_strict_order(self):
        a = kv(0, "x"); b = kv(5, "x", typ="afrl.cmasi.AAA")
        ws = n.canonicalise([a, b], n.Options(window_ms=0))
        self.assertEqual(len(ws), 2)
        self.assertEqual(ws[0][0].type, "afrl.cmasi.KeyValuePair")

    def test_window_none_single(self):
        ws = n.canonicalise([kv(0, "a"), kv(10 ** 6, "b")], n.Options(window_ms=None))
        self.assertEqual(len(ws), 1)

    def test_empty(self):
        self.assertEqual(n.canonicalise([]), [])

    def test_unsorted_input_is_time_ordered(self):
        ws = n.canonicalise([kv(1000, "b"), kv(0, "a")], n.Options(window_ms=10))
        self.assertEqual(ws[0][0].body["Value"], "a")


if __name__ == "__main__":
    unittest.main()
