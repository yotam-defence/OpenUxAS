from helpers import *  # noqa
import os
import sys
import tempfile
from uxdiff import backends


def test_find_binary_explicit_env_and_missing():
    assert backends.find_binary(sys.executable, "UXDIFF_NOPE", []) == \
        os.path.abspath(sys.executable)
    assert backends.find_binary("/no/such/bin", "UXDIFF_NOPE", ["uxas"]) is None
    assert backends.find_binary(None, "UXDIFF_NOPE", ["uxdiff-no-such"]) is None


def test_managed_process_terminates_and_detects_early_exit():
    with tempfile.TemporaryDirectory() as d:
        m = backends.Managed("sleeper", [sys.executable, "-c",
                             "import time; time.sleep(60)"], d,
                             os.path.join(d, "s.log"))
        assert m.alive()
        rc = m.terminate(5)
        assert not m.alive() and rc in backends.ZmqProcessBackend.CLEAN_RC
        m = backends.Managed("quick", [sys.executable, "-c", "print('hi')"], d,
                             os.path.join(d, "q.log"))
        m.proc.wait(timeout=30)
        assert not m.alive()
        assert m.terminate(1) == 0
        assert "hi" in m.tail()


def test_managed_missing_executable_is_run_error():
    with tempfile.TemporaryDirectory() as d:
        try:
            backends.Managed("x", ["/no/such/exe"], d, os.path.join(d, "l"))
        except backends.RunError as exc:
            assert exc.kind == "missing"
        else:
            raise AssertionError("expected RunError")


def test_real_backend_missing_binary_reported_before_zmq_needed():
    sc = make_scenario(1)
    with tempfile.TemporaryDirectory() as d:
        be = backends.ZmqProcessBackend(sc, "cpp", d, uxas_bin="/no/uxas")
        try:
            be.start()
        except backends.RunError as exc:
            assert exc.kind == "missing"
        else:
            raise AssertionError("expected RunError")
        assert be.stop() == {}


def test_resolve_bin_cli():
    import run_differential
    assert run_differential.main(["--resolve-bin", "ada", "--ada-bin", sys.executable]) == 0
    assert run_differential.main(["--resolve-bin", "ada", "--ada-bin", "/no/such/bin"]) == 1
