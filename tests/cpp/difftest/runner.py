"""Orchestration: run scenario on Ada and/or C++, normalise, diff."""
import os
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional

from difftest import ADA, CPP
from difftest.comparators import (DEFAULT_REGISTRY, ComparatorRegistry,
                                  Difference, compare_captures)
from difftest.config import render_config
from difftest.golden import GoldenError, read_golden, write_golden
from difftest.model import Scenario
from difftest.normalise import (NormaliserConfig, assign_windows,
                                normalise_capture)
from difftest.procs import (ENV_VARS, InfraError, ManagedProcess,
                            command_line, find_binary, find_free_ports)
from difftest.replay import ZmqTransport, execute_steps

MODES = ("auto", "live", "record-golden", "golden")


class Options:
    def __init__(self, mode: str = "auto", ada_bin: Optional[str] = None,
                 cpp_bin: Optional[str] = None, time_scale: float = 1.0,
                 workdir: Optional[str] = None, keep_workdir: bool = False,
                 golden_dir: Optional[str] = None, allow_stale: bool = False,
                 record_golden: bool = False,
                 startup_settle_ms: Optional[int] = None):
        if mode not in MODES:
            raise ValueError("unknown mode %r" % mode)
        self.mode = mode
        self.ada_bin, self.cpp_bin = ada_bin, cpp_bin
        self.time_scale = time_scale
        self.workdir, self.keep_workdir = workdir, keep_workdir
        self.golden_dir = golden_dir
        self.allow_stale = allow_stale
        self.record_golden = record_golden
        self.startup_settle_ms = startup_settle_ms


class ScenarioResult:
    PASS, FAIL, ERROR = "pass", "fail", "error"

    def __init__(self, scenario: str):
        self.scenario = scenario
        self.status = self.PASS
        self.mode = ""
        self.diffs: List[Difference] = []
        self.notes: List[str] = []
        self.error: Optional[str] = None
        self.counts: Dict[str, Dict[str, int]] = {}
        self.golden_path: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"scenario": self.scenario, "status": self.status,
                "mode": self.mode, "error": self.error, "notes": self.notes,
                "counts": self.counts, "golden": self.golden_path,
                "differences": [d.as_dict() for d in self.diffs]}


class ProcessBackend:
    """Starts a real binary and replays the scenario over ZeroMQ."""

    def capture(self, impl: str, scenario: Scenario, binary: str,
                workdir: str, time_scale: float,
                startup_settle_ms: Optional[int] = None
                ) -> Dict[str, List[Dict[str, Any]]]:
        """Return raw records per window (``__trailing__`` included)."""
        d = os.path.join(workdir, scenario.name, impl)
        os.makedirs(d, exist_ok=True)
        pub_port, pull_port = find_free_ports(2)
        pub = "tcp://127.0.0.1:%d" % pub_port
        pull = "tcp://127.0.0.1:%d" % pull_port
        cfg_path = os.path.join(d, "config.xml")
        with open(cfg_path, "w", encoding="utf-8") as fd:
            fd.write(render_config(impl, scenario, pub, pull))
        proc = ManagedProcess(command_line(impl, binary, cfg_path), cwd=d,
                              log_path=os.path.join(d, "output.log"))
        transport = None
        try:
            proc.start()
            transport = ZmqTransport(pub, pull)
            settle = scenario.startup_settle_ms if startup_settle_ms is None \
                else startup_settle_ms
            time.sleep(settle / 1000.0 * time_scale)
            if not proc.alive():
                raise InfraError("%s exited during startup; log tail:\n%s" %
                                 (impl, proc.log_tail()))
            start, boundaries = execute_steps(scenario, transport,
                                              time_scale=time_scale)
            time.sleep(scenario.shutdown_settle_ms / 1000.0 * time_scale)
            if not proc.alive():
                raise InfraError("%s died during the scenario; log tail:\n%s"
                                 % (impl, proc.log_tail()))
            records = transport.records()
            return assign_windows(records, boundaries, start,
                                  scenario.capture_startup)
        finally:
            if transport is not None:
                transport.close()
            proc.stop()


def make_normaliser(scenario: Scenario) -> NormaliserConfig:
    try:
        return NormaliserConfig.from_dict(scenario.normalise,
                                          service_names=scenario.services)
    except (ValueError, TypeError) as e:
        raise InfraError("scenario %s: bad normalise section: %s" %
                         (scenario.name, e))


def make_registry(scenario: Scenario,
                  base: Optional[ComparatorRegistry] = None
                  ) -> ComparatorRegistry:
    reg = (base or DEFAULT_REGISTRY).clone()
    for c in scenario.comparators:
        try:
            reg.bind_named(c["comparator"], c.get("type"), c.get("service"),
                           c.get("options"))
        except KeyError as e:
            raise InfraError("scenario %s: %s" % (scenario.name, e.args[0]))
    return reg


def _window_opts(scenario: Scenario) -> Dict[str, Dict[str, Any]]:
    return {w.name: {"ordered": w.ordered, "types": w.types}
            for w in scenario.windows}


def _normalise(scenario: Scenario, raw: Dict[str, Any],
               cfg: NormaliserConfig) -> Dict[str, Any]:
    raw = {k: v for k, v in raw.items() if k != "__trailing__"}
    return normalise_capture(raw, cfg, _window_opts(scenario))


def _bounds_check(scenario: Scenario, side: str,
                  cap: Dict[str, Any]) -> List[Difference]:
    out = []
    for w in scenario.windows:
        n = len(cap.get(w.name, []))
        if w.min_messages is not None and n < w.min_messages:
            out.append(Difference(w.name, "count", detail=(
                "%s produced %d message(s), scenario requires at least %d" %
                (side, n, w.min_messages))))
        if w.max_messages is not None and n > w.max_messages:
            out.append(Difference(w.name, "count", detail=(
                "%s produced %d message(s), scenario allows at most %d" %
                (side, n, w.max_messages))))
    return out


def resolve_mode(options: Options, ada: Optional[str], cpp: Optional[str],
                 golden_exists: bool) -> str:
    """Pick the effective mode (``auto`` -> live/golden)."""
    if options.mode != "auto":
        return options.mode
    if ada and cpp:
        return "live"
    if cpp and golden_exists:
        return "golden"
    return "auto"  # unresolvable; caller reports what is missing


def run_scenario(scenario: Scenario, options: Options,
                 backend=None, registry: Optional[ComparatorRegistry] = None,
                 workdir: Optional[str] = None) -> ScenarioResult:
    """Run one scenario in the requested mode and return its result."""
    from difftest.golden import golden_path
    backend = backend or ProcessBackend()
    res = ScenarioResult(scenario.name)
    own_workdir = workdir is None and options.workdir is None
    workdir = workdir or options.workdir or tempfile.mkdtemp(prefix="difftest-")
    try:
        cfg = make_normaliser(scenario)
        reg = make_registry(scenario, registry)
        ada = find_binary(ADA, options.ada_bin)
        cpp = find_binary(CPP, options.cpp_bin)
        if options.ada_bin and not ada:
            raise InfraError("--ada-bin %s not found or not executable" %
                             options.ada_bin)
        if options.cpp_bin and not cpp:
            raise InfraError("--cpp-bin %s not found or not executable" %
                             options.cpp_bin)
        gexists = os.path.isfile(golden_path(scenario, options.golden_dir))
        mode = resolve_mode(options, ada, cpp, gexists)
        res.mode = mode

        def cap(impl, binary):
            if not binary:
                raise InfraError("%s binary not found (use --%s-bin or %s)" %
                                 (impl, impl, ENV_VARS[impl]))
            raw = backend.capture(impl, scenario, binary, workdir,
                                  options.time_scale,
                                  options.startup_settle_ms)
            trailing = len(raw.get("__trailing__", []))
            if trailing:
                res.notes.append("%s: %d message(s) after the last window "
                                 "(not compared)" % (impl, trailing))
            return _normalise(scenario, raw, cfg)

        if mode == "auto":
            raise InfraError(
                "cannot choose a mode: need both binaries (live) or the C++ "
                "binary plus a golden (%s). Found: ada=%s cpp=%s golden=%s" %
                (golden_path(scenario, options.golden_dir), ada, cpp,
                 gexists))
        def record(expected):
            res.golden_path = write_golden(scenario, cfg, expected,
                                           options.golden_dir)
            res.notes.append("golden written: %s" % res.golden_path)

        if mode == "record-golden":
            expected = cap(ADA, ada)
            res.diffs = _bounds_check(scenario, ADA, expected)
            record(expected)
            res.counts = {n: {ADA: len(m)} for n, m in expected.items()}
        else:
            if mode == "live":
                expected = cap(ADA, ada)
                if options.record_golden:
                    record(expected)
                exp_side = ADA
            else:  # golden
                try:
                    expected = read_golden(scenario, cfg, options.golden_dir,
                                           options.allow_stale)
                except GoldenError as e:
                    raise InfraError(str(e))
                res.golden_path = golden_path(scenario, options.golden_dir)
                exp_side = "golden"
            actual = cap(CPP, cpp)
            res.counts = {n: {exp_side: len(expected.get(n, [])),
                              CPP: len(actual.get(n, []))}
                          for n in dict.fromkeys(list(expected) + list(actual))}
            res.diffs = (_bounds_check(scenario, exp_side, expected) +
                         _bounds_check(scenario, CPP, actual) +
                         compare_captures(
                             expected, actual, reg,
                             tuple(w.name for w in scenario.windows
                                   if w.ordered)))
        res.status = ScenarioResult.FAIL if res.diffs else ScenarioResult.PASS
    except InfraError as e:
        res.status, res.error = ScenarioResult.ERROR, str(e)
    finally:
        if own_workdir and not options.keep_workdir:
            shutil.rmtree(workdir, ignore_errors=True)
    return res
