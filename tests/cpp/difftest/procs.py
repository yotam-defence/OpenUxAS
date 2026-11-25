"""Locate and supervise the uxas binaries; port allocation."""
import os
import shutil
import signal
import socket
import subprocess
import time
from typing import List, Optional

from difftest import ADA, CPP

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                         "..", "..", ".."))

ENV_VARS = {ADA: "UXAS_ADA_BIN", CPP: "UXAS_BIN"}
PATH_NAMES = {ADA: ("uxas_ada", "uxas-ada"), CPP: ("uxas",)}
REPO_DEFAULTS = {ADA: (os.path.join(REPO_ROOT, "src", "ada", "uxas-ada"),),
                 CPP: (os.path.join(REPO_ROOT, "obj", "cpp", "uxas"),)}


class InfraError(Exception):
    """Environment problem (missing binary, process died, ...)."""


def find_binary(impl: str, explicit: Optional[str] = None) -> Optional[str]:
    """Binary lookup: explicit option, env var, PATH, repo build location."""
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get(ENV_VARS[impl]):
        candidates.append(os.environ[ENV_VARS[impl]])
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return os.path.abspath(c)
        w = shutil.which(c)
        if w:
            return w
        if explicit and c == explicit:
            return None  # an explicit but invalid path is an error, no guess
    for n in PATH_NAMES[impl]:
        w = shutil.which(n)
        if w:
            return w
    for c in REPO_DEFAULTS[impl]:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def find_free_ports(n: int, host: str = "127.0.0.1") -> List[int]:
    """Reserve ``n`` distinct free TCP ports (probed by bind)."""
    socks, ports = [], []
    try:
        for _ in range(n):
            s = socket.socket()
            s.bind((host, 0))
            socks.append(s)
            ports.append(s.getsockname()[1])
    finally:
        for s in socks:
            s.close()
    return ports


def command_line(impl: str, binary: str, cfg_path: str) -> List[str]:
    """Both implementations take ``-cfgPath <file>``."""
    return [binary, "-cfgPath", cfg_path]


class ManagedProcess:
    """A background uxas process with output captured to a log file."""

    def __init__(self, cmd: List[str], cwd: str, log_path: str):
        self.cmd, self.cwd, self.log_path = cmd, cwd, log_path
        self.proc: Optional[subprocess.Popen] = None
        self._log = None

    def start(self) -> None:
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(self.cmd, cwd=self.cwd,
                                     stdout=self._log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL,
                                     start_new_session=True)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def log_tail(self, nbytes: int = 2000) -> str:
        try:
            with open(self.log_path, "rb") as fd:
                fd.seek(0, os.SEEK_END)
                fd.seek(max(0, fd.tell() - nbytes))
                return fd.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def stop(self, grace: float = 3.0) -> None:
        """SIGINT (what uxas handles), then SIGTERM, then SIGKILL."""
        if self.proc is not None and self.proc.poll() is None:
            for sig, wait in ((signal.SIGINT, grace),
                              (signal.SIGTERM, grace),
                              (signal.SIGKILL, grace)):
                try:
                    os.killpg(self.proc.pid, sig)
                except (ProcessLookupError, PermissionError):
                    break
                deadline = time.monotonic() + wait
                while time.monotonic() < deadline:
                    if self.proc.poll() is not None:
                        break
                    time.sleep(0.05)
                if self.proc.poll() is not None:
                    break
        if self._log is not None:
            self._log.close()
            self._log = None
