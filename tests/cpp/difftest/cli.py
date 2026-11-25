"""Command line interface: ``python -m difftest``."""
import argparse
import json
import os
import sys
from typing import List, Optional

from difftest import EXIT_ERROR, EXIT_MISMATCH, EXIT_OK, __version__
from difftest.comparators import DEFAULT_REGISTRY, load_plugin
from difftest.procs import InfraError
from difftest.runner import MODES, Options, ScenarioResult, run_scenario
from difftest.scenario import (ScenarioError, find_scenarios, load_scenario)

HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIO_DIR = os.path.join(HERE, "scenarios")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m difftest",
        description="Differential replay of LMCP scenarios against the Ada "
                    "reference (uxas_ada) and the C++ implementation (uxas).")
    p.add_argument("scenarios", nargs="*", metavar="SCENARIO",
                   help="scenario JSON files or directories (default: the "
                        "bundled scenarios/ directory)")
    p.add_argument("--mode", choices=MODES, default="auto",
                   help="live: run both and diff; record-golden: run Ada and "
                        "store goldens/<name>.json; golden: run C++ and diff "
                        "against the golden; auto (default): live if both "
                        "binaries exist, else golden if a golden exists")
    p.add_argument("--ada-bin", help="path of uxas_ada (default: $UXAS_ADA_BIN,"
                   " PATH, src/ada/uxas-ada)")
    p.add_argument("--cpp-bin", help="path of uxas (default: $UXAS_BIN, PATH, "
                   "obj/cpp/uxas)")
    p.add_argument("--record-golden", action="store_true",
                   help="in live mode, also store the Ada output as golden")
    p.add_argument("--golden-dir", help="golden directory (default: "
                   "difftest/goldens)")
    p.add_argument("--allow-stale", action="store_true",
                   help="use a golden even if the scenario/normaliser changed")
    p.add_argument("--plugin", action="append", default=[], metavar="MOD",
                   help="comparator plug-in: .py file or module (repeatable)")
    p.add_argument("--time-scale", type=float, default=1.0,
                   help="multiply every delay/window/settle time (same for "
                        "both implementations); use >1 on slow machines")
    p.add_argument("--startup-settle-ms", type=int,
                   help="override the scenario's startup settle delay")
    p.add_argument("--workdir", help="directory for generated configs and "
                   "process logs (default: temp dir)")
    p.add_argument("--keep-workdir", action="store_true",
                   help="do not delete the temp workdir")
    p.add_argument("--report", metavar="FILE",
                   help="write a JSON report of all results")
    p.add_argument("--list-comparators", action="store_true",
                   help="list registered comparators and exit")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="print per-window message counts")
    p.add_argument("--version", action="version",
                   version="difftest " + __version__)
    return p


def _gather(paths: List[str]) -> List[str]:
    out: List[str] = []
    for p in paths or [SCENARIO_DIR]:
        if os.path.isdir(p):
            out.extend(find_scenarios(p))
        else:
            out.append(p)
    return out


def _print_result(r: ScenarioResult, verbose: bool, out=sys.stdout) -> None:
    out.write("%-6s %s (mode: %s)\n" % (r.status.upper(), r.scenario,
                                        r.mode or "-"))
    if r.error:
        for line in r.error.splitlines():
            out.write("    %s\n" % line)
    for n in r.notes:
        out.write("    note: %s\n" % n)
    if verbose:
        for w, c in r.counts.items():
            out.write("    window %-20s %s\n" % (w, ", ".join(
                "%s=%d" % kv for kv in sorted(c.items()))))
    for d in r.diffs:
        out.write("    - %s\n" % d)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        for plug in args.plugin:
            load_plugin(plug)
    except Exception as e:
        sys.stderr.write("difftest: cannot load plugin: %s\n" % e)
        return EXIT_ERROR

    if args.list_comparators:
        for n in sorted(DEFAULT_REGISTRY.named):
            doc = (DEFAULT_REGISTRY.named[n].__doc__ or "").strip()
            print("%-18s %s" % (n, doc.splitlines()[0] if doc else ""))
        for t, s, fn in DEFAULT_REGISTRY.bindings:
            print("binding type=%s service=%s -> %s" %
                  (t, s, getattr(fn, "__name__", fn)))
        return EXIT_OK

    paths = _gather(args.scenarios)
    if not paths:
        sys.stderr.write("difftest: no scenarios found\n")
        return EXIT_ERROR
    try:
        scenarios = [load_scenario(p) for p in paths]
    except ScenarioError as e:
        sys.stderr.write("difftest: %s\n" % e)
        return EXIT_ERROR
    names = [s.name for s in scenarios]
    if len(set(names)) != len(names):
        sys.stderr.write("difftest: duplicate scenario names\n")
        return EXIT_ERROR

    if args.time_scale <= 0:
        sys.stderr.write("difftest: --time-scale must be > 0\n")
        return EXIT_ERROR
    opts = Options(mode=args.mode, ada_bin=args.ada_bin, cpp_bin=args.cpp_bin,
                   time_scale=args.time_scale, workdir=args.workdir,
                   keep_workdir=args.keep_workdir,
                   golden_dir=args.golden_dir, allow_stale=args.allow_stale,
                   record_golden=args.record_golden,
                   startup_settle_ms=args.startup_settle_ms)
    results = []
    for sc in scenarios:
        try:
            r = run_scenario(sc, opts)
        except InfraError as e:  # defensive; run_scenario normally catches
            r = ScenarioResult(sc.name)
            r.status, r.error = ScenarioResult.ERROR, str(e)
        _print_result(r, args.verbose)
        results.append(r)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fd:
            json.dump([r.as_dict() for r in results], fd, indent=2,
                      sort_keys=True, default=str)
            fd.write("\n")

    n_fail = sum(r.status == ScenarioResult.FAIL for r in results)
    n_err = sum(r.status == ScenarioResult.ERROR for r in results)
    print("%d scenario(s): %d passed, %d mismatched, %d errors" %
          (len(results), len(results) - n_fail - n_err, n_fail, n_err))
    if n_err:
        return EXIT_ERROR
    return EXIT_MISMATCH if n_fail else EXIT_OK
