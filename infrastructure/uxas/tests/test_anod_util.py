"""Tests for check_gcc_min_version; e3 is stubbed so no anod install is needed."""
import importlib.util
import logging
import os
import sys
import types
import unittest
from unittest import mock

_UTIL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "src", "uxas", "anod", "util.py")


def _load_util(run):
    stubs = {}
    for name in ("e3", "e3.os", "e3.os.process", "e3.anod", "e3.anod.loader",
                 "e3.anod.context", "e3.anod.sandbox"):
        stubs[name] = types.ModuleType(name)
    stubs["e3.os.process"].Run = run
    stubs["e3.anod.loader"].AnodSpecRepository = object
    stubs["e3.anod.context"].AnodContext = object
    stubs["e3.anod.sandbox"].SandBox = object
    with mock.patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("uxas_anod_util_under_test", _UTIL)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except ImportError as e:
            raise unittest.SkipTest("util.py needs more e3 stubs: %s" % e)
    return mod


class _Run(object):
    def __init__(self, out):
        self.out = out

    def __call__(self, *a, **kw):
        return self


class GccMinVersionTests(unittest.TestCase):
    def _check(self, out):
        util = _load_util(_Run(out))
        util.Run = _Run(out)
        with self.assertLogs(level=logging.DEBUG) as cm:
            logging.getLogger().debug("sentinel")
            util.check_gcc_min_version()  # must never raise SystemExit
        return [r for r in cm.records if r.levelno >= logging.WARNING]

    def test_new_gcc_is_silent(self):
        for v in ("11\n", "13.2.0\n", "11.0.0"):
            self.assertEqual(self._check(v), [])

    def test_old_gcc_warns_without_exiting(self):
        for v in ("10.2.1\n", "9\n"):
            self.assertEqual(len(self._check(v)), 1)

    def test_unparseable_warns(self):
        self.assertEqual(len(self._check("garbage")), 1)


if __name__ == "__main__":
    unittest.main()
