"""Launch a UxAS implementation, replay a scenario over ZeroMQ, capture."""
import os
import shutil
import signal
import subprocess
import tempfile
import time
from typing import List, Optional

from difftest.codec import decode_message, encode_message
from difftest.config import build_config
from difftest.scenario import Scenario


class InfraError(RuntimeError):
    """Binary missing, failed to start, died early, pyzmq missing, ..."""


def resolve_binary(impl: str, explicit: Optional[str]) -> str:
    env = {"ada": "UXAS_ADA_BIN", "cpp": "UXAS_CPP_BIN"}[impl]
    default = {"ada": "uxas_ada", "cpp": "uxas"}[impl]
    cand = explicit or os.environ.get(env)
    path = cand if cand and os.path.sep in cand else shutil.which(cand or default)
    if cand and os.path.sep in cand and not os.access(cand, os.X_OK):
        path = None
    if not path:
        raise InfraError(
            "%s binary not found (use --%s-bin or $%s%s)" % (
                impl, impl, env,
                "; or use --use-golden to avoid running Ada" if impl == "ada" else ""))
    return os.path.abspath(path)


class Runner:
    """Runs one implementation for one scenario."""

    def __init__(self, impl: str, binary: str, scenario: Scenario,
                 workdir: Optional[str] = None, pub=None, pull=None,
                 keep_workdir=False, time_scale: float = 1.0):
        self.impl, self.sc = impl, scenario
        self.binary = os.path.abspath(binary)  # we chdir into the workdir
        self.pub, self.pull = pub or scenario.pub, pull or scenario.pull
        self.workdir = workdir or tempfile.mkdtemp(prefix="difftest-%s-" % impl)
        self.keep_workdir = keep_workdir
        self.scale = time_scale
        self.proc = None
        self.records: List[dict] = []

    # -- process management ------------------------------------------------
    def start(self):
        cfg = os.path.join(self.workdir, "cfg_%s.xml" % self.impl)
        with open(cfg, "wb") as fd:
            fd.write(build_config(self.sc, self.impl, self.pub, self.pull))
        self._log = open(os.path.join(self.workdir, "%s.log" % self.impl), "wb")
        try:
            self.proc = subprocess.Popen(
                [self.binary, "-cfgPath", cfg], cwd=self.workdir,
                stdout=self._log, stderr=subprocess.STDOUT,
                start_new_session=True)
        except OSError as e:
            raise InfraError("cannot start %s: %s" % (self.binary, e))

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            for sig, wait in ((signal.SIGINT, 5), (signal.SIGTERM, 3),
                              (signal.SIGKILL, 3)):
                try:
                    os.killpg(self.proc.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    self.proc.wait(wait)
                    break
                except subprocess.TimeoutExpired:
                    continue
        if getattr(self, "_log", None):
            self._log.close()

    def log_tail(self, n=20) -> str:
        try:
            with open(os.path.join(self.workdir, "%s.log" % self.impl),
                      errors="replace") as fd:
                return "".join(fd.readlines()[-n:])
        except OSError:
            return ""

    def cleanup(self):
        if not self.keep_workdir:
            shutil.rmtree(self.workdir, ignore_errors=True)

    # -- replay --------------------------------------------------------------
    def run(self) -> List[dict]:
        try:
            import zmq
        except ImportError:
            raise InfraError("pyzmq is required to replay scenarios "
                             "(pip install pyzmq)")
        ctx = zmq.Context()
        sub = ctx.socket(zmq.SUB)
        push = ctx.socket(zmq.PUSH)
        try:
            self.start()
            self._pump(self.sc.startup_s)  # let the process settle
            if not self.alive():
                raise InfraError("%s exited during startup (rc=%s):\n%s" % (
                    self.impl, self.proc.returncode, self.log_tail()))
            sub.setsockopt(zmq.SUBSCRIBE, b"")
            sub.connect(self.pub)
            push.setsockopt(zmq.LINGER, 1000)
            push.connect(self.pull)
            self._pump(0.3)  # SUB slow-joiner guard
            step = 0
            self.records = []
            self._poll(sub, step, 0.0)
            for spec in self.sc.messages:
                if not self.alive():
                    raise InfraError("%s died during replay (rc=%s):\n%s" % (
                        self.impl, self.proc.returncode, self.log_tail()))
                push.send(encode_message(spec, self.sc.entity_id))
                step += 1
                delay = (spec.delay_s if spec.delay_s is not None
                         else self.sc.between_messages_s)
                self._poll(sub, step, delay * self.scale)
            self._poll(sub, step, self.sc.final_s * self.scale)
            return self.records
        finally:
            sub.close(0)
            push.close(0)
            ctx.term()
            self.stop()

    def _pump(self, seconds):
        time.sleep(seconds * self.scale)

    def _poll(self, sub, step, seconds):
        """Collect messages for ``seconds`` tagging them with ``step``."""
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if sub.poll(max(0, int(remaining * 1000)) if remaining > 0 else 0):
                raw = sub.recv()
                self.records.append(decode_message(raw, step, time.time()))
                continue
            if remaining <= 0:
                break
