"""Process runner: start uxas / uxas_ada, replay, capture, tear down."""
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

from uxas_diff import scenario as scen
from uxas_diff.capture import Transport, ZmqTransport, replay

ENV_CPP = "UXAS_BIN"
ENV_ADA = "UXAS_ADA_BIN"


class RunnerError(Exception):
    pass


def find_binary(impl: str, flag: Optional[str]) -> str:
    """Resolve a binary: flag, then env (UXAS_BIN / UXAS_ADA_BIN), then PATH."""
    env, exe = (ENV_ADA, "uxas_ada") if impl == "ada" else (ENV_CPP, "uxas")
    path = flag or os.environ.get(env) or shutil.which(exe)
    if not path or not os.path.isfile(path):
        raise RunnerError(
            "cannot find %s binary: pass --%s-bin, set %s or add %s to PATH"
            % (impl, "ada" if impl == "ada" else "uxas", env, exe))
    return path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def render_config(src: str, dst: str, pub_port: int, pull_port: int) -> None:
    """Copy a config substituting ${PUB_PORT} / ${PULL_PORT}."""
    with open(src) as fd:
        text = fd.read()
    text = text.replace("${PUB_PORT}", str(pub_port)) \
               .replace("${PULL_PORT}", str(pull_port))
    with open(dst, "w") as fd:
        fd.write(text)


class Proc:
    def __init__(self, argv: List[str], cwd: str, log_path: str):
        self.argv = argv
        self.log_path = log_path
        self.log = open(log_path, "wb")
        self.p = subprocess.Popen(argv, cwd=cwd, stdout=self.log,
                                  stderr=subprocess.STDOUT)

    def alive(self) -> bool:
        return self.p.poll() is None

    def log_tail(self, n: int = 2000) -> str:
        self.log.flush()
        with open(self.log_path, "rb") as fd:
            return fd.read()[-n:].decode("utf-8", "replace")

    def stop(self) -> None:
        if self.alive():
            self.p.send_signal(signal.SIGINT)
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()
        self.log.close()


def run_impl(sc: Dict[str, Any], impl: str, bin_path: str,
             hub_bin: Optional[str] = None, keep_dir: Optional[str] = None,
             transport_factory=ZmqTransport) -> List[Dict[str, Any]]:
    """Run one implementation against the scenario; return capture records.

    ``impl`` is 'cpp' (uxas with cfg_cpp) or 'ada'. The Ada executable only
    hosts Ada services and attaches to a C++ hub that owns the
    PublishPullBridge sockets, so for 'ada' a hub uxas (``configs.hub``,
    started with ``hub_bin``) is launched first when the scenario defines one.
    """
    work = keep_dir or tempfile.mkdtemp(prefix="uxas_diff_%s_" % impl)
    os.makedirs(work, exist_ok=True)
    pub, pull = free_port(), free_port()
    procs: List[Proc] = []
    transport: Optional[Transport] = None
    try:
        def start(which: str, binary: str) -> None:
            cfg = os.path.join(work, "cfg_%s.xml" % which)
            render_config(scen.config_path(sc, which), cfg, pub, pull)
            procs.append(Proc([binary, "-cfgPath", cfg], work,
                              os.path.join(work, "%s.log" % which)))
            time.sleep(0.5)

        if impl == "ada":
            if "hub" in sc["configs"]:
                start("hub", hub_bin or find_binary("cpp", None))
            start("ada", bin_path)
        else:
            start("cpp", bin_path)

        transport = transport_factory("tcp://127.0.0.1:%d" % pub,
                                      "tcp://127.0.0.1:%d" % pull)
        records = replay(sc, transport)
        for p in procs:
            if not p.alive():
                raise RunnerError("%s exited early (rc=%s):\n%s" % (
                    p.argv[0], p.p.returncode, p.log_tail()))
        return records
    finally:
        if transport is not None:
            transport.close()
        for p in reversed(procs):
            p.stop()
        if keep_dir is None:
            shutil.rmtree(work, ignore_errors=True)
