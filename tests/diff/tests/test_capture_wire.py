import sys
import types
import unittest
from unittest import mock

import _path  # noqa: F401
from uxas_diff import capture


class BuildWireTest(unittest.TestCase):
    def test_hex_step(self):
        self.assertEqual(capture.build_wire({"hex": "aabb"}), b"\xaa\xbb")

    def test_delay_only_step(self):
        self.assertIsNone(capture.build_wire({"delay_ms": 10}))

    def test_object_step_uses_entity_and_service_ids(self):
        calls = {}

        class FakeMessage:
            def __init__(self, obj, source_entity_id, source_service_id):
                calls.update(obj=obj, ent=source_entity_id,
                             svc=source_service_id)

            def pack(self):
                return b"packed"

        fake = types.ModuleType("pylmcp.message")
        fake.Message = FakeMessage
        with mock.patch.object(capture, "_pylmcp"), \
                mock.patch.object(capture, "_build_object",
                                  return_value="OBJ"), \
                mock.patch.dict(sys.modules, {"pylmcp.message": fake}):
            wire = capture.build_wire({"object": {"class": "X"}}, 7, 9)
        self.assertEqual(wire, b"packed")
        self.assertEqual(calls, {"obj": "OBJ", "ent": 7, "svc": 9})


class DecodeWireTest(unittest.TestCase):
    def test_record_fields(self):
        class FakeObj:
            def as_dict(self):
                return {"a": 1}

        class FakeMessage:
            address, descriptor, content_type = "addr", "desc", "ct"
            source_group, source_entity_id, source_service_id = "g", 1, 2
            obj = FakeObj()

            @staticmethod
            def unpack(raw):
                assert raw == b"raw"
                return FakeMessage()

        fake = types.ModuleType("pylmcp.message")
        fake.Message = FakeMessage
        with mock.patch.object(capture, "_pylmcp"), \
                mock.patch.dict(sys.modules, {"pylmcp.message": fake}):
            rec = capture.decode_wire(b"raw")
        self.assertEqual(rec, {
            "address": "addr", "descriptor": "desc", "content_type": "ct",
            "source_group": "g", "source_entity_id": 1,
            "source_service_id": 2, "obj": {"a": 1}})


class ZmqTransportTest(unittest.TestCase):
    def setUp(self):
        self.zmq = mock.MagicMock()
        self.zmq.SUB, self.zmq.PUSH = "SUB", "PUSH"
        self.zmq.SUBSCRIBE, self.zmq.POLLIN = "SUBSCRIBE", "POLLIN"
        self.sub, self.push = mock.MagicMock(), mock.MagicMock()
        ctx = self.zmq.Context.return_value
        ctx.socket.side_effect = lambda kind: {"SUB": self.sub,
                                               "PUSH": self.push}[kind]
        self.ctx = ctx
        with mock.patch.dict(sys.modules, {"zmq": self.zmq}):
            self.tr = capture.ZmqTransport("tcp://p:1", "tcp://q:2")

    def test_setup(self):
        self.sub.setsockopt.assert_called_once_with("SUBSCRIBE", b"")
        self.sub.connect.assert_called_once_with("tcp://p:1")
        self.push.connect.assert_called_once_with("tcp://q:2")

    def test_send(self):
        self.tr.send(b"x")
        self.push.send.assert_called_once_with(b"x")

    def test_poll(self):
        self.sub.poll.return_value = 1
        self.sub.recv.return_value = b"msg"
        self.assertEqual(self.tr.poll(50), b"msg")
        self.sub.poll.assert_called_with(50, "POLLIN")
        self.sub.poll.return_value = 0
        self.assertIsNone(self.tr.poll(50))

    def test_close(self):
        self.tr.close()
        self.sub.close.assert_called_once_with(0)
        self.push.close.assert_called_once_with(0)
        self.ctx.term.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
