"""Starts the Ada and C++ stacks, replays a scenario and captures output.

The runner is written against two small injectable interfaces so it can be
tested offline:

* ``launcher(argv, name) -> handle`` with ``handle.stop()`` / ``handle.alive()``
* ``transport_factory(endpoint, capture) -> transport`` with
  ``open() / send(msg) / captured() / close()``
"""
import os
import signal
import subprocess
import tempfile
import time

from . import comparators, golden, normalize, report


class RunError(Exception):
    pass


class Process(object):
    def __init__(self, argv, name, log_dir=None):
        self.name = name
        self.argv = argv
        self.log = None
        if log_dir:
            self.log = open(os.path.join(log_dir, name + ".log"), "wb")
        try:
            self.p = subprocess.Popen(argv, stdout=self.log or subprocess.DEVNULL,
                                      stderr=subprocess.STDOUT)
        except OSError as e:
            raise RunError("cannot start %s (%s): %s" % (name, argv[0], e))

    def alive(self):
        return self.p.poll() is None

    def stop(self):
        if self.alive():
            self.p.send_signal(signal.SIGINT)
            try:
                self.p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()
        if self.log:
            self.log.close()


def default_launcher(log_dir=None):
    return lambda argv, name: Process(argv, name, log_dir)


def default_transport_factory(endpoint, capture):
    from . import live
    return live.ZmqTransport(endpoint, capture)


def run_side(scenario, side, bin_path, launcher, transport_factory, sleep=time.sleep,
             bin_hub=None):
    """Run one stack and return the raw captured messages.

    ``side`` is ``"ada"`` (starts the C++ hub with ``ada_hub_cfg`` if given,
    then ``uxas_ada``) or ``"cpp"`` (starts ``uxas``).
    """
    procs = []
    try:
        if side == "ada":
            if scenario.ada_hub_cfg:
                if not bin_hub:
                    raise RunError("scenario has ada_hub_cfg: --cpp-bin is needed to host the Ada bus")
                procs.append(launcher([bin_hub, "-cfgPath", scenario.ada_hub_cfg], "ada_hub"))
                sleep(scenario.startup_delay_ms / 1000.0)
            procs.append(launcher([bin_path, "-cfgPath", scenario.ada_cfg], "ada"))
        else:
            procs.append(launcher([bin_path, "-cfgPath", scenario.cpp_cfg], "cpp"))
        sleep(scenario.startup_delay_ms / 1000.0)
        for p in procs:
            if not p.alive():
                raise RunError("%s exited prematurely" % getattr(p, "name", side))
        t = transport_factory(scenario.endpoint, scenario.capture)
        t.open()
        try:
            sleep(0.2)  # let SUB/PUSH connect (slow-joiner)
            for m in scenario.messages:
                sleep(m.delay_ms / 1000.0)
                t.send(m)
            sleep(scenario.settle_ms / 1000.0)
            return t.captured()
        finally:
            t.close()
    finally:
        for p in reversed(procs):
            p.stop()


def compare(scenario, ada_raw, cpp_raw, notes=None):
    """Canonicalise both captures and run the scenario's comparators."""
    opts = scenario.normalization_options()
    for plugin in scenario.plugins:
        p = plugin
        if p.endswith(".py") and not os.path.isabs(p):
            p = os.path.join(scenario.base_dir, p)
        comparators.load_plugin(p)
    a = normalize.canonicalise(ada_raw, opts)
    c = normalize.canonicalise(cpp_raw, opts)
    diffs = comparators.run_all(scenario.comparators, a, c)
    stats = {"ada_messages": len(ada_raw), "cpp_messages": len(cpp_raw),
             "ada_windows": len(a), "cpp_windows": len(c),
             "comparators": ",".join(s["name"] for s in scenario.comparators)}
    return report.Report(scenario.name, diffs, stats, notes)


def obtain_ada(scenario, ada_bin, cpp_bin, golden_dir, record, allow_stale,
               launcher, transport_factory, sleep=time.sleep):
    """Return ``(raw_ada_messages, notes)`` from golden cache or a live run.

    Policy: with ``record`` the Ada side is always run live and stored.
    Otherwise, a valid golden file is preferred; if there is none and an
    Ada binary is available the reference is recorded.
    """
    notes = []
    fp = scenario.reference_fingerprint()
    if golden_dir and not record:
        try:
            msgs = golden.load(golden_dir, scenario.name, fp, allow_stale)
            notes.append("Ada reference from golden file %s"
                         % golden.golden_path(golden_dir, scenario.name))
            return msgs, notes
        except golden.GoldenMissing:
            if not ada_bin:
                raise
        except golden.GoldenStale:
            if not ada_bin:
                raise
            notes.append("golden file stale; re-recording")
    if not ada_bin:
        raise RunError("no Ada binary (--ada-bin) and no golden directory given")
    msgs = run_side(scenario, "ada", ada_bin, launcher, transport_factory, sleep, cpp_bin)
    notes.append("Ada reference captured live")
    if golden_dir:
        path = golden.save(golden_dir, scenario.name, fp, msgs)
        notes.append("recorded golden file %s" % path)
    return msgs, notes
