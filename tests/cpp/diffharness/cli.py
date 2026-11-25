"""Command line interface."""
import argparse
import os
import sys
from typing import List, Optional

from diffharness import codec
from diffharness.comparators import (UnknownComparator, available_comparators,
                                     compare_records, load_plugins)
from diffharness.diffing import unified_diff
from diffharness.golden import GoldenError, load_golden, save_golden
from diffharness.scenario import ScenarioError, load_scenario

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GOLDEN = os.path.join(HERE, "golden")

EXIT_OK, EXIT_MISMATCH, EXIT_ERROR = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="diffharness",
        description="Differential replay harness: run the same scenario "
                    "against the C++ uxas and the Ada uxas_ada and diff the "
                    "canonicalised outbound LMCP.")
    p.add_argument("--cpp-bin", help="path to the C++ uxas executable")
    p.add_argument("--ada-bin", help="path to the Ada uxas_ada executable")
    p.add_argument("--scenario",
                   help="scenario file (.json/.yaml) or bare name resolved "
                        "in diffharness/scenarios/")
    p.add_argument("--golden-dir", default=DEFAULT_GOLDEN,
                   help="directory of cached golden captures "
                        "(default: %(default)s)")
    p.add_argument("--update-golden", action="store_true",
                   help="record captures of the binaries that are run and "
                        "store them as golden files")
    p.add_argument("--reference", choices=("live", "golden"),
                   default="live",
                   help="'live': run both binaries; 'golden': use the cached "
                        "golden capture as the Ada reference (no --ada-bin "
                        "needed)")
    p.add_argument("--settle-delay", type=float, default=2.0,
                   help="seconds to wait after launching a binary before "
                        "replaying (default: %(default)s)")
    p.add_argument("--plugin", action="append", default=[],
                   help="python module registering comparators (repeatable)")
    p.add_argument("--list-comparators", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="validate the scenario and print the generated "
                        "configs, then exit")
    p.add_argument("--context", type=int, default=3,
                   help="diff context lines")
    return p


def resolve_scenario_path(arg: str) -> str:
    if os.path.isfile(arg):
        return arg
    for ext in ("", ".json", ".yaml", ".yml"):
        cand = os.path.join(HERE, "scenarios", arg + ext)
        if os.path.isfile(cand):
            return cand
    return arg


def main(argv: Optional[List[str]] = None, out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        load_plugins(args.plugin)
        if args.list_comparators:
            out.write("\n".join(available_comparators()) + "\n")
            return EXIT_OK
        if not args.scenario:
            err.write("error: --scenario is required\n")
            return EXIT_ERROR
        sc = load_scenario(resolve_scenario_path(args.scenario))

        if args.dry_run:
            from diffharness.config_gen import build_config
            for impl in ("cpp", "ada"):
                out.write("--- %s config ---\n%s" % (
                    impl, build_config(sc, impl).decode()))
            return EXIT_OK

        if args.update_golden and args.reference == "golden":
            err.write("error: --update-golden requires --reference live\n")
            return EXIT_ERROR
        if not args.cpp_bin:
            err.write("error: --cpp-bin is required\n")
            return EXIT_ERROR
        if args.reference == "live" and not args.ada_bin:
            err.write("error: --ada-bin is required with --reference live "
                      "(use --reference golden when no Ada toolchain is "
                      "available)\n")
            return EXIT_ERROR

        from diffharness.runner import run_implementation
        log = lambda m: err.write(m + "\n")
        cpp = run_implementation(sc, "cpp", args.cpp_bin,
                                 settle_delay=args.settle_delay, log=log)
        if args.reference == "golden":
            ada = load_golden(args.golden_dir, sc.name, "ada")
            ref_label = "ada(golden)"
        else:
            ada = run_implementation(sc, "ada", args.ada_bin,
                                     settle_delay=args.settle_delay, log=log)
            ref_label = "ada"

        if args.update_golden:
            save_golden(args.golden_dir, sc.name, "cpp", cpp)
            p = save_golden(args.golden_dir, sc.name, "ada", ada)
            err.write("golden files updated under %s\n" % os.path.dirname(p))

        return report(sc, ada, cpp, ref_label, out, args.context)
    except (ScenarioError, GoldenError, UnknownComparator,
            codec.MissingDependency) as e:
        err.write("error: %s\n" % (e.args[0] if e.args else e))
        return EXIT_ERROR
    except Exception as e:  # RunError etc.
        from diffharness.runner import RunError
        if isinstance(e, RunError):
            err.write("error: %s\n" % e)
            return EXIT_ERROR
        raise


def report(sc, ada, cpp, ref_label: str, out, context: int = 3) -> int:
    equal, exp, act = compare_records(ada, cpp, sc.comparator)
    diff = unified_diff(exp, act, ref_label, "cpp", context)
    if equal and not diff:
        out.write("PASS %s: %d ada / %d cpp messages equivalent\n"
                  % (sc.name, len(ada), len(cpp)))
        return EXIT_OK
    out.write(diff)
    out.write("FAIL %s: outputs differ (%s vs cpp)\n" % (sc.name, ref_label))
    return EXIT_MISMATCH
