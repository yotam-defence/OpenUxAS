import unittest
from unittest import mock

from difftool import live
from difftool.scenario import Message


class FakeObject(object):
    def __init__(self, cls, **fields):
        self.cls, self.fields = cls, fields


class FakeMessage(object):
    last = None

    def __init__(self, obj=None, **kw):
        self.obj, self.kw = obj, kw
        FakeMessage.last = self

    def pack(self):
        return b"packed"

    @classmethod
    def unpack(cls, raw):
        if raw == b"bad":
            raise ValueError("boom")
        return cls()

    def as_dict(self):
        return {"address": "a", "descriptor": "d", "content_type": "lmcp",
                "source_group": "g", "source_entitiy_id": 7,
                "source_service_id": 3, "obj": {"k": 1}}


def _msg(address=None, fields=None):
    return Message(cls="afrl.cmasi.KeyValuePair", fields=fields or {"Key": "k"},
                   source_entity_id=1, source_service_id=2, source_group="g",
                   address=address)


class LiveTests(unittest.TestCase):
    def test_build_nested_and_lists(self):
        o = live._build({"_class": "X", "a": [1, {"_class": "Y"}]}, FakeObject)
        self.assertEqual(o.cls, "X")
        self.assertEqual(o.fields["a"][0], 1)
        self.assertEqual(o.fields["a"][1].cls, "Y")

    def test_build_requires_class(self):
        with self.assertRaises(live.LiveError):
            live._build({"a": 1}, FakeObject)

    def test_encode_address_only_when_set(self):
        self.assertEqual(live.encode(_msg(), FakeObject, FakeMessage), b"packed")
        self.assertNotIn("address", FakeMessage.last.kw)
        live.encode(_msg(address="addr"), FakeObject, FakeMessage)
        self.assertEqual(FakeMessage.last.kw["address"], "addr")

    def test_decode_maps_source_entity_typo(self):
        d = live.decode(b"ok", 5.0, FakeMessage)
        self.assertEqual(d["source_entity_id"], 7)
        self.assertEqual(d["t_ms"], 5.0)

    def test_captured_keeps_undecodable(self):
        with mock.patch.object(live, "_import_live",
                               return_value=(mock.Mock(), FakeObject, FakeMessage)):
            t = live.ZmqTransport({"pub": "p", "push": "q"}, ["x"])
        t.raw = [(1.0, b"ok"), (2.0, b"bad")]
        out = t.captured()
        self.assertEqual(out[0]["source_entity_id"], 7)
        self.assertEqual(out[1]["address"], "<undecodable>")
        self.assertEqual(out[1]["obj"]["hex"], b"bad".hex())


if __name__ == "__main__":
    unittest.main()
