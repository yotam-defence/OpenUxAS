"""Deterministic replay of a scenario against one implementation.

Determinism comes from (a) a fixed ``startup_ms`` before the first message,
(b) a ``settle_ms`` wait after every injected message during which outbound
messages are collected into that message's *window*, and (c) a final
``drain_ms``.  Everything that touches the outside world (processes, ZeroMQ,
clock, sleeping) is injected through :class:`RunContext`, so the whole flow
is unit-testable with the fakes in ``testing.py``.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .bus import Bus, ClientBus, HubBus
from .canonical import CanonSettings
from .capture import (Capture, GoldenError, RawFrame, load_golden,
                      save_golden)
from .comparators import ComparatorSet, Difference
from .config import build_config
from .differ import DiffResult, diff_messages
from .messages import decode_frame, envelope_key
from .process import ManagedProcess, SubprocessLauncher
from .replay import build_frame
from .scenario import Scenario


class RunError(Exception):
    """Infrastructure failure (binary missing, process died, ...)."""


def default_bus_factory(side: str, sc: Scenario) -> Bus:
    if side == "ada":
        return HubBus(sc.pub_url, sc.pull_url)
    return ClientBus(sc.pub_url, sc.pull_url)


@dataclass
class RunContext:
    binaries: dict = field(default_factory=dict)       # side -> path or None
    workdir: Optional[str] = None
    launcher: object = field(default_factory=SubprocessLauncher)
    bus_factory: Callable[[str, Scenario], Bus] = default_bus_factory
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    decoder: Callable = decode_frame
    log: Callable[[str], None] = lambda s: None
    poll_ms: int = 10
    keep_workdir: bool = False


class _EchoFilter:
    """Drops messages that are the replayed input echoed back by a bridge."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.pending: Counter = Counter()

    def sent(self, frame: bytes) -> None:
        if self.mode == "bytes":
            self.pending[frame] += 1
        elif self.mode == "envelope":
            self.pending[envelope_key(frame)] += 1

    def is_echo(self, frame: bytes) -> bool:
        if self.mode == "none":
            return False
        k = frame if self.mode == "bytes" else envelope_key(frame)
        if self.pending[k] > 0:
            self.pending[k] -= 1
            return True
        return False


def _assign_windows(frames: List[RawFrame], mode: str) -> None:
    if mode == "step":
        return
    for f in frames:
        f.window = 0 if mode == "all" else int(f.t_ms // int(mode[6:]))


def run_side(side: str, sc: Scenario, ctx: RunContext) -> Capture:
    """Start the implementation for ``side``, replay, capture, stop it."""
    binary = ctx.binaries.get(side)
    if not binary:
        raise RunError("no %s binary available (use --%s or, for the Ada "
                       "reference, golden files)" %
                       (side, "uxas-ada" if side == "ada" else "uxas"))
    own_tmp = ctx.workdir is None
    workdir = tempfile.mkdtemp(prefix="run-diff-%s-" % side) if own_tmp \
        else os.path.join(ctx.workdir, side)
    os.makedirs(workdir, exist_ok=True)
    cfg_path = os.path.join(workdir, "cfg_%s.xml" % side)
    with open(cfg_path, "wb") as fd:
        fd.write(build_config(sc, side))

    t = sc.timing
    cap = Capture(side=side, scenario=sc.name,
                  fingerprint=sc.capture_fingerprint(side))
    echo = _EchoFilter(sc.capture.echo_filter)
    bus = ctx.bus_factory(side, sc)
    proc: Optional[ManagedProcess] = None
    state = {"window": 0}
    t0 = ctx.clock()

    def collect() -> None:
        now = (ctx.clock() - t0) * 1000.0
        for f in bus.poll():
            if not echo.is_echo(f):
                cap.frames.append(RawFrame(state["window"], now, f))

    def wait(ms: int) -> None:
        end = ctx.clock() + ms / 1000.0
        while True:
            collect()
            remaining = end - ctx.clock()
            if remaining <= 0:
                break
            ctx.sleep(min(ctx.poll_ms / 1000.0, remaining))

    def check_alive(what: str) -> None:
        if proc is not None and not proc.alive():
            raise RunError("%s exited unexpectedly %s:\n%s" %
                           (side, what, proc.log_tail()))

    try:
        argv = [binary, "-cfgPath", cfg_path]
        log_path = os.path.join(workdir, "%s.log" % side)
        ctx.log("[%s] %s" % (side, " ".join(argv)))
        if side == "ada":
            bus.open()           # Ada connects to sockets we must own
        proc = ctx.launcher.start(argv, workdir, log_path)
        wait(t.startup_ms)
        check_alive("during startup")
        if side != "ada":
            bus.open()
            wait(t.settle_ms)    # let SUB/PUSH connections establish
            check_alive("while connecting")
        elif sc.services_for("ada") and bus.subscribers_seen() == 0:
            ctx.log("[ada] warning: no subscription seen from uxas_ada "
                    "after startup_ms=%d" % t.startup_ms)

        for i, step in enumerate(sc.steps):
            wait(step.delay_ms)
            frame = build_frame(step, sc.entity_id)
            state["window"] = i + 1
            echo.sent(frame)
            bus.inject(frame)
            ctx.log("[%s] step %d %s" % (side, i + 1, step.label))
            wait(t.settle_ms if step.settle_ms is None else step.settle_ms)
            check_alive("after step %d" % (i + 1))
        wait(t.drain_ms)
        check_alive("while draining")
    finally:
        cap.log_tail = proc.log_tail() if proc is not None else ""
        try:
            bus.close()
        finally:
            if proc is not None:
                proc.stop(t.shutdown_ms / 1000.0)
            if own_tmp and not ctx.keep_workdir:
                shutil.rmtree(workdir, ignore_errors=True)
    _assign_windows(cap.frames, sc.capture.window)
    return cap


def obtain_capture(side: str, sc: Scenario, ctx: RunContext, mode: str,
                   golden_dir: Optional[str], update_golden: bool,
                   allow_stale: bool) -> Capture:
    """Get a side's capture: from golden file and/or by a live run."""
    fp = sc.capture_fingerprint(side)
    if mode in ("auto", "golden") and golden_dir and not update_golden:
        try:
            cap = load_golden(golden_dir, sc.name, side, fp, allow_stale)
            ctx.log("[%s] using golden capture" % side)
            return cap
        except GoldenError as e:
            if mode == "golden":
                raise RunError(str(e))
            ctx.log("[%s] golden unusable (%s); running live" % (side, e))
    elif mode == "golden":
        raise RunError("golden mode needs --golden-dir (and no "
                       "--update-golden)")
    cap = run_side(side, sc, ctx)
    if update_golden:
        if not golden_dir:
            raise RunError("--update-golden needs --golden-dir")
        ctx.log("[%s] wrote %s" % (side, save_golden(golden_dir, cap)))
    return cap


def compare_captures(sc: Scenario, ref: Capture, got: Capture,
                     ctx: Optional[RunContext] = None) -> DiffResult:
    decoder = ctx.decoder if ctx else decode_frame
    result = diff_messages(
        sc.name, ref.decode(decoder), got.decode(decoder),
        ComparatorSet(sc.comparators),
        CanonSettings.from_scenario(sc.normalise),
        sc.capture.exclude_types)
    for cap in (ref, got):
        if cap.source == "golden":
            result.notes.append("%s output taken from golden file" %
                                cap.side)
    for cap, n in ((ref, result.ref_count), (got, result.got_count)):
        if n < sc.capture.min_messages:
            result.differences.append(Difference(
                0, "count", "*", "%s produced %d message(s), scenario "
                "requires at least %d" % (cap.side, n,
                                          sc.capture.min_messages)))
    return result


def record_cpp_golden(sc: Scenario, ctx: RunContext, golden_dir: str
                      ) -> Capture:
    """Record the C++ side only as a *regression* golden (not Ada output).

    Used when ``uxas_ada`` is unavailable.  The golden is labelled with its
    provenance so it can never be mistaken for the Ada reference.
    """
    cap = run_side("cpp", sc, ctx)
    cap.meta = {
        "recorded_from": "cpp",
        "reference_is_ada": False,
        "note": "Recorded from the C++ uxas binary because the Ada "
                "reference (uxas_ada) was not available. This is a "
                "regression baseline, NOT Ada output. Re-record the "
                "reference with: tests/cpp/run-diff run %s --update-golden "
                "(needs uxas and uxas_ada)." % sc.name,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "message_count": len(cap.frames),
    }
    if len(cap.frames) < sc.capture.min_messages:
        raise RunError("recorded only %d message(s), scenario requires %d"
                       % (len(cap.frames), sc.capture.min_messages))
    ctx.log("[cpp] wrote %s" % save_golden(golden_dir, cap))
    return cap


def run_scenario(sc: Scenario, ctx: RunContext, ada: str = "auto",
                 cpp: str = "live", golden_dir: Optional[str] = None,
                 update_golden: bool = False,
                 allow_stale: bool = False) -> DiffResult:
    """Full differential run: reference (Ada) vs candidate (C++)."""
    cpp_regression = False
    if update_golden:
        # (re)record the reference from uxas_ada; the C++ capture below is
        # recorded as well so both goldens are in sync.
        ref = obtain_capture("ada", sc, ctx, ada, golden_dir, True,
                             allow_stale)
    else:
        try:
            ref = obtain_capture("ada", sc, ctx, ada, golden_dir, False,
                                 allow_stale)
        except (RunError, GoldenError) as e:
            # No Ada reference (no golden, no binary): fall back to the
            # committed C++ regression golden, if any.
            if ada != "auto" or ctx.binaries.get("ada") or not golden_dir:
                raise
            try:
                ref = load_golden(golden_dir, sc.name, "cpp",
                                  sc.capture_fingerprint("cpp"),
                                  allow_stale)
            except GoldenError:
                raise RunError("%s; and no C++ regression golden either" % e)
            cpp_regression = True
    if ref.source == "live":
        ctx.sleep(0.2)          # let the sockets of side 1 be released
    got = obtain_capture("cpp", sc, ctx, cpp, golden_dir, update_golden,
                         allow_stale)
    result = compare_captures(sc, ref, got, ctx)
    if cpp_regression:
        result.notes.insert(0, "REGRESSION GATE: no Ada reference "
                            "available; compared live C++ against the "
                            "committed C++-recorded golden (%s)" %
                            ref.meta.get("recorded_at", "unknown date"))
    return result
