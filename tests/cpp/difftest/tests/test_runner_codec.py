"""Hermetic unit tests for difftest.codec and difftest.runner."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from difftest import codec, runner


def _spec(**kw):
    d = dict(hex=None, lmcp={"type": "T", "fields": {}},
             source_entity_id=None, source_service_id=0)
    d.update(kw)
    return SimpleNamespace(**d)


class CodecTests(unittest.TestCase):
    RAW = b"addr$ct|desc|grp|100|7$payload"

    def test_split_header(self):
        h, payload = codec.split_header(self.RAW)
        self.assertEqual(h["address"], "addr")
        self.assertEqual(h["content_type"], "ct")
        self.assertEqual(h["descriptor"], "desc")
        self.assertEqual(h["source_group"], "grp")
        self.assertEqual(h["source_entity_id"], 100)
        self.assertEqual(h["source_service_id"], 7)
        self.assertEqual(payload, b"payload")

    def test_split_header_payload_with_dollar(self):
        _, payload = codec.split_header(b"a$c|d|g|1|2$pay$load")
        self.assertEqual(payload, b"pay$load")

    def test_split_header_malformed(self):
        for raw in (b"nodollar", b"a$b|c$p"):
            with self.assertRaises(ValueError):
                codec.split_header(raw)

    def test_jsonable(self):
        class Odd:
            def __repr__(self):
                return "ODD"
        out = codec.jsonable({1: (b"\x01\xff", [None, True, 2, 1.5, "s"]),
                              "o": Odd()})
        self.assertEqual(out, {"1": ["01ff", [None, True, 2, 1.5, "s"]],
                               "o": "ODD"})

    def test_encode_hex(self):
        self.assertEqual(codec.encode_message(_spec(hex="0aff"), 1),
                         b"\x0a\xff")

    def test_encode_entity_fallback_and_override(self):
        fake_msg = mock.MagicMock()
        fake_msg.return_value.pack.return_value = b"x"
        fake_obj = mock.MagicMock()
        with mock.patch.object(codec, "_pylmcp",
                               return_value=(fake_obj, fake_msg)):
            codec.encode_message(_spec(source_service_id=3), 42)
            self.assertEqual(fake_msg.call_args.kwargs["source_entity_id"], 42)
            self.assertEqual(fake_msg.call_args.kwargs["source_service_id"], 3)
            codec.encode_message(_spec(source_entity_id=5), 42)
            self.assertEqual(fake_msg.call_args.kwargs["source_entity_id"], 5)

    def test_decode_malformed(self):
        rec = codec.decode_message(b"garbage", step=2, t=1.0)
        self.assertEqual(rec["descriptor"], "<malformed>")
        self.assertEqual(rec["source_entity_id"], -1)
        self.assertTrue(rec["decode_error"].startswith("malformed header"))
        self.assertIsNone(rec["obj"])
        self.assertEqual(rec["step"], 2)

    def test_decode_without_pylmcp(self):
        with mock.patch.object(codec, "_pylmcp", side_effect=ImportError("x")):
            rec = codec.decode_message(self.RAW, step=1, t=2.0)
        self.assertEqual(rec["descriptor"], "desc")
        self.assertIn("ImportError", rec["decode_error"])
        self.assertIsNone(rec["obj"])
        self.assertEqual(rec["raw_hex"], self.RAW.hex())

    def test_decode_success(self):
        fake_msg = mock.MagicMock()
        fake_msg.unpack.return_value.obj.as_dict.return_value = {"a": (1, 2)}
        with mock.patch.object(codec, "_pylmcp",
                               return_value=(mock.MagicMock(), fake_msg)):
            rec = codec.decode_message(self.RAW)
        self.assertEqual(rec["obj"], {"a": [1, 2]})
        self.assertIsNone(rec["decode_error"])


@unittest.skipUnless(os.name == "posix", "POSIX process semantics")
class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="difftest-ut-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.sc = SimpleNamespace(pub="tcp://127.0.0.1:1", pull="tcp://127.0.0.1:2")
        patcher = mock.patch.object(runner, "build_config", return_value=b"<x/>")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _script(self, body):
        path = os.path.join(self.tmp, "fake_bin")
        with open(path, "w") as fd:
            fd.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
        return path

    def _runner(self, binary, **kw):
        return runner.Runner("cpp", binary, self.sc, workdir=self.tmp, **kw)

    def test_resolve_binary_errors_and_hints(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UXAS_ADA_BIN", None)
            os.environ.pop("UXAS_CPP_BIN", None)
            with self.assertRaises(runner.InfraError) as ada:
                runner.resolve_binary("ada", "/nonexistent/uxas_ada")
            self.assertIn("--use-golden", str(ada.exception))
            with self.assertRaises(runner.InfraError) as cpp:
                runner.resolve_binary("cpp", "/nonexistent/uxas")
            self.assertNotIn("--use-golden", str(cpp.exception))

    def test_resolve_binary_env_override(self):
        path = self._script("exit 0")
        with mock.patch.dict(os.environ, {"UXAS_CPP_BIN": path}):
            self.assertEqual(runner.resolve_binary("cpp", None),
                             os.path.abspath(path))

    def test_start_failure_raises_infra_error(self):
        r = self._runner(os.path.join(self.tmp, "missing"))
        with self.assertRaises(runner.InfraError):
            r.start()
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "cfg_cpp.xml")))
        r.stop()

    def test_start_alive_stop(self):
        r = self._runner(self._script("exec sleep 30"))
        r.start()
        self.assertTrue(r.alive())
        r.stop()
        self.assertFalse(r.alive())

    def test_stop_never_started_is_noop(self):
        self._runner("/bin/true").stop()

    def test_stop_escalates_signals(self):
        r = self._runner("/bin/true")
        r.proc = mock.MagicMock(pid=123)
        r.proc.poll.return_value = None
        r.proc.wait.side_effect = [subprocess.TimeoutExpired("x", 1),
                                   subprocess.TimeoutExpired("x", 1), 0]
        with mock.patch.object(runner.os, "killpg") as killpg:
            r.stop()
        import signal
        self.assertEqual([c.args[1] for c in killpg.call_args_list],
                         [signal.SIGINT, signal.SIGTERM, signal.SIGKILL])

    def test_stop_stops_on_process_lookup_error(self):
        r = self._runner("/bin/true")
        r.proc = mock.MagicMock(pid=123)
        r.proc.poll.return_value = None
        with mock.patch.object(runner.os, "killpg",
                               side_effect=ProcessLookupError) as killpg:
            r.stop()
        self.assertEqual(killpg.call_count, 1)

    def test_log_tail(self):
        r = self._runner("/bin/true")
        self.assertEqual(r.log_tail(), "")
        with open(os.path.join(self.tmp, "cpp.log"), "w") as fd:
            fd.write("".join("line%d\n" % i for i in range(30)))
        self.assertEqual(len(r.log_tail().splitlines()), 20)
        self.assertEqual(r.log_tail(5).splitlines()[-1], "line29")
        self.assertEqual(len(r.log_tail(5).splitlines()), 5)

    def test_cleanup(self):
        d = tempfile.mkdtemp(prefix="difftest-ut-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        runner.Runner("cpp", "/bin/true", self.sc, workdir=d,
                      keep_workdir=True).cleanup()
        self.assertTrue(os.path.isdir(d))
        runner.Runner("cpp", "/bin/true", self.sc, workdir=d).cleanup()
        self.assertFalse(os.path.isdir(d))

    def test_run_without_pyzmq(self):
        r = self._runner("/bin/true")
        with mock.patch.dict(sys.modules, {"zmq": None}):
            with self.assertRaises(runner.InfraError) as cm:
                r.run()
        self.assertIn("pyzmq", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
