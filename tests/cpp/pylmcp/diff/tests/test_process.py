import os
import signal
import sys
import time

import pytest

import conftest  # noqa: F401  (sets sys.path)
from pylmcp.diff.process import (ManagedProcess, ProcessError,
                                 SubprocessHandle, SubprocessLauncher)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="needs POSIX")


def _py(code):
    return [sys.executable, "-u", "-c", code]


def _wait_for(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_normal_exit_and_log_tail(tmp_path):
    h = SubprocessHandle(_py("print('hi')"), str(tmp_path),
                         str(tmp_path / "p.log"))
    assert _wait_for(lambda: not h.alive())
    assert h.stop() == 0
    assert "hi" in h.log_tail()


def test_log_tail_limits_lines_and_missing_log(tmp_path):
    log = tmp_path / "p.log"
    h = SubprocessHandle(_py("print('a'); print('b'); print('c')"),
                         str(tmp_path), str(log))
    assert _wait_for(lambda: not h.alive())
    h.stop()
    assert h.log_tail(lines=2) == "b\nc\n"
    log.unlink()
    assert h.log_tail() == ""


def test_start_failure_raises_process_error(tmp_path):
    with pytest.raises(ProcessError):
        SubprocessHandle(["/nonexistent/binary"], str(tmp_path),
                         str(tmp_path / "p.log"))


def test_stop_graceful_on_sigint(tmp_path):
    code = ("import time\nprint('ready')\n"
            "while True: time.sleep(0.05)\n")
    h = SubprocessHandle(_py(code), str(tmp_path), str(tmp_path / "p.log"))
    assert _wait_for(lambda: "ready" in h.log_tail())
    assert h.stop(timeout_s=3.0) is not None
    assert not h.alive()


def test_stop_escalates_to_sigkill(tmp_path):
    code = ("import signal, time\n"
            "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "print('ready')\n"
            "while True: time.sleep(0.05)\n")
    h = SubprocessHandle(_py(code), str(tmp_path), str(tmp_path / "p.log"))
    assert _wait_for(lambda: "ready" in h.log_tail())
    assert h.stop(timeout_s=0.3) == -signal.SIGKILL


def test_stop_after_exit_is_harmless(tmp_path):
    h = SubprocessHandle(_py("pass"), str(tmp_path), str(tmp_path / "p.log"))
    assert _wait_for(lambda: not h.alive())
    assert h.stop() == 0
    assert h.stop() == 0


def test_launcher_returns_managed_process(tmp_path):
    h = SubprocessLauncher().start(_py("pass"), str(tmp_path),
                                   str(tmp_path / "p.log"))
    try:
        assert isinstance(h, ManagedProcess)
    finally:
        h.stop()
