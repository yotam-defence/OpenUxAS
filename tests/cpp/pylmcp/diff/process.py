"""Process control for the binaries under test (injectable for tests)."""
from __future__ import annotations

import os
import signal
import subprocess
from typing import List, Optional


class ProcessError(Exception):
    pass


class ManagedProcess:
    """Interface implemented by SubprocessHandle and test fakes."""

    def alive(self) -> bool:
        raise NotImplementedError

    def stop(self, timeout_s: float = 3.0) -> Optional[int]:
        raise NotImplementedError

    def log_tail(self, lines: int = 20) -> str:
        return ""


class SubprocessHandle(ManagedProcess):
    def __init__(self, argv: List[str], cwd: str, log_path: str,
                 env: Optional[dict] = None) -> None:
        self.argv = argv
        self.log_path = log_path
        self._log = open(log_path, "wb")
        try:
            self.proc = subprocess.Popen(
                argv, cwd=cwd, stdout=self._log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        except OSError as e:
            self._log.close()
            raise ProcessError("cannot start %s: %s" % (argv[0], e))

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self, timeout_s: float = 3.0) -> Optional[int]:
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGINT)
                self.proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait()
            except ProcessLookupError:
                pass
        self._log.close()
        return self.proc.returncode

    def log_tail(self, lines: int = 20) -> str:
        try:
            with open(self.log_path, "r", errors="replace") as fd:
                return "".join(fd.readlines()[-lines:])
        except OSError:
            return ""


class SubprocessLauncher:
    """Starts real binaries; replace with a fake in unit tests."""

    def start(self, argv: List[str], cwd: str, log_path: str
              ) -> ManagedProcess:
        return SubprocessHandle(argv, cwd, log_path)
