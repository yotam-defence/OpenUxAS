"""Run one implementation against a scenario and capture its output.

The binary is started with the generated config containing a
LmcpObjectNetworkPublishPullBridge (same mechanism as pylmcp.server.Server).
The harness connects a SUB socket to the bridge's PUB address (capture) and a
PUSH socket to its PULL address (replay).  Everything is driven from a single
thread: while waiting for the next scheduled replay step the SUB socket is
polled, so capture timestamps and replay schedule share one monotonic clock.
"""
import os
import signal
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

from diffharness import codec
from diffharness.config_gen import build_config
from diffharness.scenario import Scenario


class RunError(RuntimeError):
    pass


def _zmq():
    try:
        import zmq
    except ImportError:
        raise codec.MissingDependency(
            "pyzmq is required to replay scenarios against binaries "
            "(pip install pyzmq). '--reference golden' only avoids running "
            "the Ada side; the C++ side still needs pyzmq. The unit tests "
            "do not need it.")
    return zmq


def _connect_addr(addr: str) -> str:
    # The bridge config binds ('tcp://*:5560' style is accepted by uxas);
    # clients must connect to a concrete host.
    return addr.replace("tcp://*", "tcp://127.0.0.1")


def stop_process(proc: subprocess.Popen, grace_s: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=grace_s)
        return
    except subprocess.TimeoutExpired:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run_implementation(scenario: Scenario, impl: str, binary: str,
                       settle_delay: float = 2.0,
                       extra_args: Optional[List[str]] = None,
                       workdir: Optional[str] = None,
                       log=None) -> List[Dict[str, Any]]:
    """Launch ``binary``, replay the scenario, return decoded records."""
    zmq = _zmq()
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        raise RunError("%s binary not found or not executable: %s"
                       % (impl, binary))

    # Pre-encode every step so encoding errors surface before launching.
    wire = [codec.encode_step(s, scenario.entity_id)
            for s in scenario.replay]

    records: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="diffharness-%s-" % impl) as tmp:
        cfg = os.path.join(tmp, "cfg_%s.xml" % impl)
        with open(cfg, "wb") as fd:
            fd.write(build_config(scenario, impl))
        out = open(os.path.join(tmp, "stdout.log"), "wb")
        proc = subprocess.Popen(
            [os.path.abspath(binary), "-cfgPath", cfg] + list(extra_args or []),
            stdout=out, stderr=subprocess.STDOUT,
            cwd=workdir or tmp)
        ctx = zmq.Context()
        sub = ctx.socket(zmq.SUB)
        push = ctx.socket(zmq.PUSH)
        sub.setsockopt(zmq.LINGER, 0)
        push.setsockopt(zmq.LINGER, 1000)
        try:
            sub.connect(_connect_addr(scenario.pub_address))
            sub.setsockopt(zmq.SUBSCRIBE, b"")
            push.connect(_connect_addr(scenario.pull_address))
            poller = zmq.Poller()
            poller.register(sub, zmq.POLLIN)

            # Settle: let the binary bind its sockets and services start.
            # Messages received here are discarded (startup chatter).
            _drain(poller, sub, time.monotonic() + settle_delay, None,
                   proc, 0.0)
            if proc.poll() is not None:
                raise RunError("%s exited early with code %s (log: %s)"
                               % (impl, proc.returncode,
                                  _tail(os.path.join(tmp, "stdout.log"))))

            t0 = time.monotonic()
            due = 0.0
            for step, data in zip(scenario.replay, wire):
                due += step.delay_ms / 1000.0
                _drain(poller, sub, t0 + due, records, proc, t0)
                push.send(data)
            # Capture until a quiet period passes with no traffic, bounded
            # by max_wait_ms after the last replayed message.
            deadline = time.monotonic() + scenario.capture.max_wait_ms / 1000.0
            quiet = scenario.capture.quiet_ms / 1000.0
            while time.monotonic() < deadline:
                got = _drain(poller, sub,
                             min(time.monotonic() + quiet, deadline),
                             records, proc, t0, return_on_msg=True)
                if not got:
                    break
        finally:
            sub.close()
            push.close()
            ctx.term()
            stop_process(proc)
            out.close()
            if log:
                log("%s: captured %d messages" % (impl, len(records)))
    ignored = set(scenario.capture.ignore_types)
    return [r for r in records
            if r["obj"].get("$type") not in ignored]


def _drain(poller, sub, until: float, records: Optional[list], proc,
           t0: float, return_on_msg: bool = False) -> bool:
    """Poll ``sub`` until monotonic time ``until``.

    Received messages are appended to ``records`` (dropped if None).  Returns
    True if returning early because a message arrived (``return_on_msg``).
    """
    while True:
        remaining = until - time.monotonic()
        if remaining <= 0:
            return False
        if poller.poll(timeout=min(remaining, 0.05) * 1000):
            raw = sub.recv()
            if records is not None:
                t_ms = int((time.monotonic() - t0) * 1000)
                records.append(codec.decode_wire(raw, t_ms))
            if return_on_msg:
                return True
        elif proc.poll() is not None and records is not None:
            return False


def _tail(path: str, n: int = 20) -> str:
    try:
        with open(path, "rb") as fd:
            return b"\n".join(fd.read().splitlines()[-n:]).decode(
                "utf-8", "replace")
    except OSError:
        return "<no log>"
