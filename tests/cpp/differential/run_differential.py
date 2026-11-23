#!/usr/bin/env python3
"""Ada-vs-C++ UxAS differential replay harness (CLI).

See README.md.  Exit codes: 0 match, 1 differences, 2 usage/scenario error,
3 a binary was missing/crashed/timed out, 4 golden file problem.
"""

import argparse
import inspect
import json
import os
import shutil
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from uxdiff import comparators, runner, scenario as scn  # noqa: E402


def build_parser():
    p = argparse.ArgumentParser(
        prog="run_differential.py",
        description="Replay one LMCP scenario through uxas_ada and uxas and "
                    "diff the canonicalised outputs.")
    p.add_argument("scenario", nargs="?", help="scenario JSON file")
    p.add_argument("--cpp-bin", help="C++ uxas binary (env UXAS_CPP_BIN, "
                                     "default: 'uxas' on PATH)")
    p.add_argument("--ada-bin", help="Ada uxas_ada binary (env UXAS_ADA_BIN, "
                                     "default: 'uxas_ada' on PATH)")
    p.add_argument("--golden", help="use this golden file as the reference "
                                    "instead of running the Ada binary")
    p.add_argument("--record-golden", metavar="FILE",
                   help="run the reference side and cache its canonical "
                        "output in FILE")
    p.add_argument("--record-only", action="store_true",
                   help="with --record-golden: do not run the candidate")
    p.add_argument("--golden-side", choices=("ada", "cpp"), default="ada",
                   help="side recorded by --record-golden (default ada)")
    p.add_argument("--ignore-golden-digest", action="store_true",
                   help="accept golden files recorded from an older "
                        "version of the scenario")
    p.add_argument("--cpp-only", action="store_true",
                   help="Ada-less smoke mode: run only the C++ side twice, "
                        "check clean runs, non-error heartbeat capture and "
                        "determinism. Does NOT check Ada parity.")
    p.add_argument("--plugin", action="append", default=[],
                   help="comparator plug-in (file.py or module); repeatable")
    p.add_argument("--workdir", help="keep configs/logs in this directory "
                                     "(default: temp dir, removed on success)")
    p.add_argument("--report", metavar="FILE", help="write a JSON report")
    p.add_argument("--list-comparators", action="store_true")
    p.add_argument("--self-test", action="store_true",
                   help="run the harness unit tests (no binaries/zmq needed)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def self_test(argv=()):
    tests = os.path.join(HERE, "tests")
    try:
        import pytest  # noqa: F401
    except ImportError:
        return _mini_runner(tests)
    import pytest
    return int(pytest.main(["-q", "-p", "no:cacheprovider", tests] + list(argv)))


def _mini_runner(tests_dir):
    """Fallback when pytest is missing: run fixture-free test_* functions."""
    import importlib.util
    sys.path.insert(0, tests_dir)
    failed = passed = 0
    for fn in sorted(os.listdir(tests_dir)):
        if not (fn.startswith("test_") and fn.endswith(".py")):
            continue
        spec = importlib.util.spec_from_file_location(fn[:-3],
                                                      os.path.join(tests_dir, fn))
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            failed += 1
            print("FAIL importing %s" % fn)
            traceback.print_exc()
            continue
        for name, func in sorted(vars(mod).items()):
            if name.startswith("test_") and callable(func):
                if inspect.signature(func).parameters:
                    continue  # needs pytest fixtures
                try:
                    func()
                    passed += 1
                except Exception:
                    failed += 1
                    print("FAIL %s::%s" % (fn, name))
                    traceback.print_exc()
    print("%d passed, %d failed (mini runner)" % (passed, failed))
    return 1 if failed or not passed else 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        for plug in args.plugin:
            comparators.load_plugin(plug)
        if args.list_comparators:
            print("\n".join(comparators.list_comparators()))
            return 0
        if not args.scenario:
            print("error: scenario file required", file=sys.stderr)
            return runner.EXIT_USAGE
        sc = scn.load_scenario(args.scenario)
        for plug in sc.plugins:
            comparators.load_plugin(
                plug if os.path.isabs(plug) or not plug.endswith(".py")
                else os.path.join(os.path.dirname(sc.path), plug))
        comparators.get_comparator(sc.comparator, sc.comparator_options)
    except (scn.ScenarioError, KeyError, ImportError, OSError, TypeError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return runner.EXIT_USAGE

    workdir, temp = runner.make_workdir(args.workdir)
    factory = runner.real_backend_factory(sc, workdir, args.cpp_bin,
                                          args.ada_bin)
    if args.cpp_only:
        if args.golden or args.record_golden:
            print("error: --cpp-only cannot be combined with --golden/"
                  "--record-golden", file=sys.stderr)
            return runner.EXIT_USAGE
        result = runner.run_cpp_only(sc, factory)
    else:
        result = runner.run_differential(
            sc, factory, golden=args.golden, record_golden=args.record_golden,
            golden_side=args.golden_side,
            ignore_golden_digest=args.ignore_golden_digest,
            record_only=args.record_only)

    for m in result.messages:
        print(m, file=sys.stderr)
    if result.report is not None:
        print(result.report.format())
    if args.cpp_only:
        print("Ada reference unavailable: parity not checked "
              "(C++-only smoke %s)" %
              ("passed" if result.exit_code == runner.EXIT_MATCH else "FAILED"))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fd:
            json.dump(result.as_dict(), fd, indent=2, sort_keys=True)
    if temp and result.exit_code == runner.EXIT_MATCH:
        shutil.rmtree(workdir, ignore_errors=True)
    elif result.exit_code != runner.EXIT_MATCH:
        print("logs/configs kept in %s" % workdir, file=sys.stderr)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
