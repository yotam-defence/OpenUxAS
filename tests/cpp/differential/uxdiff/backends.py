"""Execution backends.

A backend runs one *side* (cpp or ada) of a scenario.  The runner only uses
this tiny interface, so the unit tests drive it with :class:`FakeBackend`
(in-process, virtual clock, no sockets, no binaries).

    start()            launch everything, raises RunError on failure
    send(envelope)     inject one message on the bus
    wait(ms)           let ``ms`` pass (real or virtual), collecting output
    drain()            return list of (raw_bytes, t_ms) captured since last call
    check()            raise RunError if a managed process died unexpectedly
    stop()             terminate; return dict with return codes
"""

import os
import shutil
import signal
import socket
import subprocess
import time

from . import config


class RunError(RuntimeError):
    """A side failed to run (missing binary, crash, timeout, ...)."""

    def __init__(self, msg, kind="failure"):
        RuntimeError.__init__(self, msg)
        self.kind = kind  # 'missing' | 'crash' | 'timeout' | 'failure'


class Backend(object):
    side = "?"

    def start(self):
        raise NotImplementedError

    def send(self, envelope):
        raise NotImplementedError

    def wait(self, ms):
        raise NotImplementedError

    def drain(self):
        raise NotImplementedError

    def check(self):
        pass

    def stop(self):
        return {}


class FakeBackend(Backend):
    """In-process stand-in for a UxAS binary.

    ``behaviour(envelope, t_ms) -> list[bytes]`` returns raw bus messages the
    fake emits in reaction to each injected message.  ``spontaneous`` is a
    list of ``(t_ms, raw)`` emitted on the virtual clock regardless of input.
    Failure injection: ``crash_at_ms`` and ``fail_start``.
    """

    def __init__(self, side="fake", behaviour=None, spontaneous=(),
                 echo=True, crash_at_ms=None, fail_start=None,
                 jitter_reverse=False):
        self.side = side
        self.behaviour = behaviour
        self.spontaneous = sorted(spontaneous, key=lambda x: x[0])
        self.echo = echo
        self.crash_at_ms = crash_at_ms
        self.fail_start = fail_start
        self.jitter_reverse = jitter_reverse
        self.now = 0.0
        self.sent = []
        self._out = []
        self._spont_idx = 0
        self.stopped = False
        self.started = False

    def start(self):
        if self.fail_start:
            raise RunError(self.fail_start, "missing")
        self.started = True

    def send(self, envelope):
        self.sent.append(envelope)
        out = []
        if self.echo:
            out.append(envelope.pack())
        if self.behaviour:
            out.extend(self.behaviour(envelope, self.now))
        if self.jitter_reverse:
            out.reverse()
        for raw in out:
            self._out.append((raw, self.now))

    def wait(self, ms):
        end = self.now + ms
        while (self._spont_idx < len(self.spontaneous) and
               self.spontaneous[self._spont_idx][0] <= end):
            t, raw = self.spontaneous[self._spont_idx]
            self._out.append((raw, t))
            self._spont_idx += 1
        self.now = end

    def check(self):
        if self.crash_at_ms is not None and self.now >= self.crash_at_ms:
            raise RunError("fake process crashed at %sms" % self.crash_at_ms,
                           "crash")

    def drain(self):
        out, self._out = self._out, []
        return out

    def stop(self):
        self.stopped = True
        return {"fake": 0}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_binary(explicit, env_var, names):
    cand = explicit or os.environ.get(env_var)
    if cand:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return os.path.abspath(cand)
        found = shutil.which(cand)
        if found:
            return found
        return None
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    return None


class Managed(object):
    """A launched process with its log file."""

    def __init__(self, name, argv, cwd, log_path):
        self.name = name
        self.argv = argv
        self.log_path = log_path
        self._log = open(log_path, "wb")
        try:
            self.proc = subprocess.Popen(
                argv, cwd=cwd, stdout=self._log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            self._log.close()
            raise RunError("cannot execute %s: %s" % (argv[0], exc), "missing")

    def alive(self):
        return self.proc.poll() is None

    def terminate(self, grace_s):
        """SIGINT -> SIGTERM -> SIGKILL; returns the return code."""
        if self.alive():
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(self.proc.pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    self.proc.wait(timeout=grace_s)
                    break
                except subprocess.TimeoutExpired:
                    continue
        else:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)  # reap stragglers
            except (ProcessLookupError, PermissionError):
                pass
        rc = self.proc.poll()
        self._log.close()
        return rc

    def tail(self, n=2000):
        try:
            with open(self.log_path, "rb") as fd:
                return fd.read()[-n:].decode("utf-8", "replace")
        except OSError:
            return ""


class ZmqProcessBackend(Backend):
    """Runs real binaries and talks to the bus over ZeroMQ.

    cpp: one ``uxas`` hosting bridge + services.
    ada: a ``uxas`` hub hosting only the PublishPull bridge, plus
         ``uxas_ada`` with the services, connected to the hub's addresses.
    The harness connects SUB to AddressPUB and PUSH to AddressPULL.
    """

    #: exit codes treated as clean after we send SIGINT (130/-2) or SIGTERM
    CLEAN_RC = (0, None, -signal.SIGINT, -signal.SIGTERM, 130, 143)

    def __init__(self, scenario, side, workdir, uxas_bin=None, ada_bin=None):
        self.scenario = scenario
        self.side = side
        self.workdir = os.path.join(workdir, side)
        os.makedirs(self.workdir, exist_ok=True)
        self.uxas_bin = uxas_bin
        self.ada_bin = ada_bin
        self.procs = []
        self.ctx = self.pub_sock = self.push_sock = self.poller = None
        self._zmq = None
        self._out = []
        self._t0 = time.monotonic()
        self.deadline = None

    # -- helpers ---------------------------------------------------------
    def _bin_opts(self, which):
        return self.scenario.binaries.get(which, {})

    def _argv(self, binary, which, cfg):
        tmpl = self._bin_opts(which).get("args", ["-cfgPath", "{CFG}"])
        return [binary] + [a.replace("{CFG}", cfg) for a in tmpl]

    def _write_cfg(self, name, xml):
        path = os.path.join(self.workdir, name)
        with open(path, "wb") as fd:
            fd.write(xml)
        return path

    def _launch(self, name, binary, which, cfg):
        m = Managed(name, self._argv(binary, which, cfg), self.workdir,
                    os.path.join(self.workdir, name + ".log"))
        self.procs.append(m)
        return m

    def _import_zmq(self):
        try:
            import zmq  # lazy: only real runs need pyzmq
        except ImportError:
            raise RunError("pyzmq is required for real runs "
                           "(pip install pyzmq)", "missing")
        self._zmq = zmq

    # -- Backend API -----------------------------------------------------
    def start(self):
        timing = self.scenario.timing
        self.deadline = time.monotonic() + timing["timeout_s"]
        cpp = find_binary(self.uxas_bin, "UXAS_CPP_BIN", ["uxas"])
        if self.side == "ada" and self._bin_opts("ada").get("hub", "cpp") != "cpp":
            raise RunError("only binaries.ada.hub='cpp' is supported", "failure")
        needs_cpp = (self.side == "cpp" or
                     self._bin_opts("ada").get("hub", "cpp") == "cpp")
        if needs_cpp:
            if not cpp:
                raise RunError("C++ 'uxas' binary not found (use --cpp-bin or "
                               "UXAS_CPP_BIN)", "missing")
        if self.side == "ada":
            ada = find_binary(self.ada_bin, "UXAS_ADA_BIN", ["uxas_ada"])
            if not ada:
                raise RunError("Ada 'uxas_ada' binary not found (use "
                               "--ada-bin/UXAS_ADA_BIN, or --golden)",
                               "missing")
        self._import_zmq()
        pub = "tcp://127.0.0.1:%d" % free_port()
        pull = "tcp://127.0.0.1:%d" % free_port()
        self.pub_addr, self.pull_addr = pub, pull
        settle = timing["startup_settle_ms"]
        try:
            if self.side == "cpp":
                xml = config.make_config(self.scenario, "cpp", pub, pull,
                                         self.workdir)
                self._launch("uxas", cpp, "cpp",
                             self._write_cfg("uxas.xml", xml))
            else:
                if self._bin_opts("ada").get("hub", "cpp") == "cpp":
                    hub = config.make_config(self.scenario, "ada", pub, pull,
                                             self.workdir,
                                             include_services=False)
                    self._launch("uxas_hub", cpp, "cpp",
                                 self._write_cfg("hub.xml", hub))
                    self._settle(settle)
                    self.check()
                xml = config.make_config(self.scenario, "ada", pub, pull,
                                         self.workdir)
                self._launch("uxas_ada", ada, "ada",
                             self._write_cfg("uxas_ada.xml", xml))
            self._open_sockets(pub, pull)
            self._settle(settle)
            self.check()
        except Exception:
            self.stop()
            raise

    def _open_sockets(self, pub, pull):
        zmq = self._zmq
        self.ctx = zmq.Context()
        self.pub_sock = self.ctx.socket(zmq.SUB)
        self.pub_sock.setsockopt(zmq.LINGER, 0)
        self.pub_sock.setsockopt(zmq.SUBSCRIBE, b"")
        self.pub_sock.connect(pub)
        self.push_sock = self.ctx.socket(zmq.PUSH)
        self.push_sock.setsockopt(zmq.LINGER, 1000)
        self.push_sock.setsockopt(zmq.SNDTIMEO, 5000)
        self.push_sock.connect(pull)
        self.poller = zmq.Poller()
        self.poller.register(self.pub_sock, zmq.POLLIN)

    def _settle(self, ms):
        """Sleep ``ms`` while collecting messages and watching processes."""
        end = time.monotonic() + ms / 1000.0
        while True:
            now = time.monotonic()
            if now > self.deadline:
                raise RunError("scenario timeout (%ss)" %
                               self.scenario.timing["timeout_s"], "timeout")
            remaining = end - now
            if remaining <= 0:
                break
            if self.poller is not None:
                if self.poller.poll(timeout=min(remaining, 0.05) * 1000):
                    self._collect_nowait()
            else:
                time.sleep(min(remaining, 0.05))
            self.check()

    def _collect_nowait(self):
        if self.pub_sock is None:
            return
        while True:
            try:
                raw = self.pub_sock.recv(self._zmq.NOBLOCK)
            except self._zmq.Again:
                return
            self._out.append((raw, (time.monotonic() - self._t0) * 1000))

    def send(self, envelope):
        try:
            self.push_sock.send(envelope.pack())
        except self._zmq.ZMQError as exc:
            raise RunError("send failed: %s" % exc, "failure")

    def wait(self, ms):
        self._settle(ms)

    def check(self):
        for m in self.procs:
            if not m.alive():
                raise RunError("%s exited early with rc=%s; log tail:\n%s" %
                               (m.name, m.proc.returncode, m.tail()), "crash")

    def drain(self):
        out, self._out = self._out, []
        return out

    def stop(self):
        grace = self.scenario.timing["shutdown_grace_s"]
        rcs = {}
        # one last collection of anything already queued
        self._collect_nowait()
        for m in reversed(self.procs):
            alive = m.alive()
            rc = m.terminate(grace)
            clean = (rc in self.CLEAN_RC) if alive else (rc == 0)
            rcs[m.name] = {"rc": rc, "was_running": alive, "clean": clean}
        for s in (self.pub_sock, self.push_sock):
            if s is not None:
                s.close(0)
        if self.ctx is not None:
            self.ctx.term()
        self.procs = []
        return rcs
