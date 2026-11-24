import os
import sys
import tempfile
import unittest
from unittest import mock

import _path  # noqa: F401
from uxas_diff import runner
from uxas_diff.runner import Proc, RunnerError


class ProcTest(unittest.TestCase):
    def test_log_tail_and_stop(self):
        with tempfile.TemporaryDirectory() as d:
            p = Proc([sys.executable, "-c",
                      "import time; print('hello', flush=True); "
                      "time.sleep(60)"], d, os.path.join(d, "p.log"))
            for _ in range(100):
                if "hello" in p.log_tail():
                    break
                import time
                time.sleep(0.05)
            self.assertIn("hello", p.log_tail())
            self.assertTrue(p.alive())
            p.stop()
            self.assertFalse(p.alive())
            self.assertTrue(p.log.closed)


class FakeProc:
    instances = []
    dead = ()

    def __init__(self, argv, cwd, log_path):
        self.argv = argv
        self.cwd = cwd
        self.stopped = False
        self.p = mock.Mock(returncode=3)
        self.index = len(FakeProc.instances)
        FakeProc.instances.append(self)

    def alive(self):
        return self.index not in FakeProc.dead

    def log_tail(self):
        return "TAIL"

    def stop(self):
        self.stopped = True


class FakeTransport:
    last = None

    def __init__(self, pub, pull):
        self.addrs = (pub, pull)
        self.closed = False
        FakeTransport.last = self

    def close(self):
        self.closed = True


class RunImplTest(unittest.TestCase):
    def setUp(self):
        FakeProc.instances = []
        FakeProc.dead = ()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name in ("cpp", "ada", "hub"):
            with open(os.path.join(self.tmp.name, "cfg_%s.xml" % name),
                      "w") as fd:
                fd.write("pub=${PUB_PORT} pull=${PULL_PORT}")
        self.sc = {"name": "s", "messages": [], "capture": {},
                   "configs": {"cpp": "x", "ada": "x", "hub": "x"}}
        patches = [
            mock.patch.object(runner, "Proc", FakeProc),
            mock.patch.object(runner.time, "sleep"),
            mock.patch.object(runner, "replay", return_value=["rec"]),
            mock.patch.object(runner.scen, "config_path",
                              side_effect=lambda sc, w: os.path.join(
                                  self.tmp.name, "cfg_%s.xml" % w)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_impl(self, impl, **kw):
        return runner.run_impl(self.sc, impl, "/bin/" + impl,
                               transport_factory=FakeTransport, **kw)

    def test_cpp_path(self):
        self.assertEqual(self.run_impl("cpp"), ["rec"])
        self.assertEqual(len(FakeProc.instances), 1)
        argv = FakeProc.instances[0].argv
        self.assertEqual(argv[0], "/bin/cpp")
        self.assertEqual(argv[1], "-cfgPath")
        self.assertTrue(FakeProc.instances[0].stopped)
        self.assertTrue(FakeTransport.last.closed)

    def test_ada_starts_hub_first(self):
        self.run_impl("ada", hub_bin="/bin/hub")
        self.assertEqual([p.argv[0] for p in FakeProc.instances],
                         ["/bin/hub", "/bin/ada"])
        self.assertTrue(all(p.stopped for p in FakeProc.instances))

    def test_early_exit_raises(self):
        FakeProc.dead = (0,)
        with self.assertRaises(RunnerError) as cm:
            self.run_impl("cpp")
        self.assertIn("rc=3", str(cm.exception))
        self.assertIn("TAIL", str(cm.exception))
        self.assertTrue(FakeProc.instances[0].stopped)
        self.assertTrue(FakeTransport.last.closed)

    def test_keep_dir_retained_and_config_rendered(self):
        keep = os.path.join(self.tmp.name, "keep")
        self.run_impl("cpp", keep_dir=keep)
        cfg = os.path.join(keep, "cfg_cpp.xml")
        self.assertTrue(os.path.isdir(keep))
        with open(cfg) as fd:
            text = fd.read()
        pub, pull = FakeTransport.last.addrs
        self.assertEqual(text, "pub=%s pull=%s" % (
            pub.rsplit(":", 1)[1], pull.rsplit(":", 1)[1]))

    def test_tmp_workdir_removed(self):
        self.run_impl("cpp")
        self.assertFalse(os.path.exists(FakeProc.instances[0].cwd))


if __name__ == "__main__":
    unittest.main()
