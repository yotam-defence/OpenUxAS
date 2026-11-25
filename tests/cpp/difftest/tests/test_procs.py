import os
import signal
import socket
import sys
import time

import pytest

from difftest import ADA, CPP
from difftest import procs
from difftest.procs import (ENV_VARS, InfraError, ManagedProcess,
                            command_line, find_binary, find_free_ports)


def _script(path, body="#!/bin/sh\nexit 0\n", mode=0o755):
    path.write_text(body)
    path.chmod(mode)
    return str(path)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """No env vars, empty PATH, no repo-default binaries."""
    for v in ENV_VARS.values():
        monkeypatch.delenv(v, raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setattr(procs, "REPO_DEFAULTS",
                        {ADA: (str(tmp_path / "none-ada"),),
                         CPP: (str(tmp_path / "none-cpp"),)})
    return tmp_path


def test_find_binary_explicit(isolated):
    b = _script(isolated / "mybin")
    assert find_binary(CPP, b) == os.path.abspath(b)


def test_find_binary_explicit_invalid_beats_env(isolated, monkeypatch):
    monkeypatch.setenv(ENV_VARS[CPP], _script(isolated / "envbin"))
    assert find_binary(CPP, str(isolated / "missing")) is None


def test_find_binary_env_var(isolated, monkeypatch):
    b = _script(isolated / "envbin")
    monkeypatch.setenv(ENV_VARS[CPP], b)
    assert find_binary(CPP) == os.path.abspath(b)


def test_find_binary_path_lookup_and_ada_names(isolated, monkeypatch):
    d = isolated / "bin"
    d.mkdir()
    _script(d / "uxas")
    _script(d / "uxas-ada")
    monkeypatch.setenv("PATH", str(d))
    assert find_binary(CPP) == str(d / "uxas")
    assert find_binary(ADA) == str(d / "uxas-ada")


def test_find_binary_repo_default(isolated, monkeypatch):
    b = _script(isolated / "built-uxas")
    monkeypatch.setattr(procs, "REPO_DEFAULTS", {ADA: (), CPP: (b,)})
    assert find_binary(CPP) == b


def test_find_binary_none_and_non_executable(isolated, monkeypatch):
    assert find_binary(CPP) is None
    monkeypatch.setenv(ENV_VARS[CPP], _script(isolated / "noexec", mode=0o644))
    assert find_binary(CPP) is None


def test_find_free_ports():
    ports = find_free_ports(5)
    assert len(ports) == 5 and len(set(ports)) == 5
    for p in ports:
        assert 0 < p < 65536
        with socket.socket() as s:
            s.bind(("127.0.0.1", p))
    assert find_free_ports(0) == []


def test_command_line():
    for impl in (ADA, CPP):
        assert command_line(impl, "/b/uxas", "c.xml") == \
            ["/b/uxas", "-cfgPath", "c.xml"]


def test_infra_error_is_exception():
    assert issubclass(InfraError, Exception)


def _wait_for(proc, text, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if text in proc.log_tail():
            return
        time.sleep(0.02)
    raise AssertionError("child never printed %r: %r" % (text, proc.log_tail()))


def _managed(tmp_path, code):
    return ManagedProcess([sys.executable, "-c", code], str(tmp_path),
                          str(tmp_path / "out.log"))


def test_managed_process_lifecycle(tmp_path):
    p = _managed(tmp_path, "import time; print('ready', flush=True); "
                           "time.sleep(60)")
    assert not p.alive()
    p.start()
    try:
        _wait_for(p, "ready")
        assert p.alive()
    finally:
        p.stop(grace=1)
    assert not p.alive()
    assert p._log is None
    p.stop(grace=0.1)  # idempotent


def test_stop_never_started_is_noop(tmp_path):
    _managed(tmp_path, "pass").stop()


def test_log_tail_truncates_and_missing(tmp_path):
    p = _managed(tmp_path, "print('x' * 500, flush=True)")
    assert p.log_tail() == ""
    p.start()
    try:
        p.proc.wait(timeout=5)
        assert p.log_tail(nbytes=100) == "x" * 99 + "\n"
    finally:
        p.stop()


def test_stop_escalates_to_sigkill(tmp_path):
    p = _managed(tmp_path,
                 "import signal, time\n"
                 "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
                 "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                 "print('ready', flush=True)\n"
                 "time.sleep(60)\n")
    p.start()
    try:
        _wait_for(p, "ready")
    finally:
        p.stop(grace=0.3)
    assert p.proc.returncode == -signal.SIGKILL


def test_stop_escalates_to_sigterm(tmp_path):
    p = _managed(tmp_path,
                 "import signal, time\n"
                 "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
                 "print('ready', flush=True)\n"
                 "time.sleep(60)\n")
    p.start()
    try:
        _wait_for(p, "ready")
    finally:
        p.stop(grace=0.3)
    assert p.proc.returncode == -signal.SIGTERM


def test_stop_kills_process_group(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    p = _managed(tmp_path,
                 "import subprocess, sys, time\n"
                 "g = subprocess.Popen([sys.executable, '-c', "
                 "'import time; time.sleep(60)'])\n"
                 "open(%r, 'w').write(str(g.pid))\n"
                 "print('ready', flush=True)\n"
                 "time.sleep(60)\n" % str(pidfile))
    p.start()
    try:
        _wait_for(p, "ready")
        gpid = int(pidfile.read_text())
    finally:
        p.stop(grace=0.5)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(gpid, 0)
        except ProcessLookupError:
            return
        # a zombie child of a dead parent is reaped by init; keep polling
        time.sleep(0.05)
    raise AssertionError("grandchild %d survived stop()" % gpid)
