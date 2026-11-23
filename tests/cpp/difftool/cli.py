"""Command line interface (used by tests/cpp/run-diff)."""
import argparse
import json
import os
import sys
import unittest

from . import (EXIT_DIFF, EXIT_GOLDEN, EXIT_INFRA, EXIT_MATCH, EXIT_USAGE,
               comparators, golden, runner, scenario)

HERE = os.path.dirname(os.path.abspath(__file__))


def build_parser():
    p = argparse.ArgumentParser(
        prog="run-diff",
        description="Ada-vs-C++ differential replay harness for UxAS.",
        epilog="Exit codes: 0 match, 1 differences, 2 usage/scenario error, "
               "3 infrastructure error (binary/ZeroMQ/launch), 4 golden file "
               "missing or stale.")
    p.add_argument("--selftest", action="store_true",
                   help="run the offline unit tests and exit")
    p.add_argument("--scenario", metavar="FILE", help="scenario JSON file")
    p.add_argument("--ada-bin", metavar="PATH", help="uxas_ada executable")
    p.add_argument("--cpp-bin", metavar="PATH", help="uxas (C++) executable")
    p.add_argument("--golden", metavar="DIR",
                   help="golden-file directory: use cached Ada output if present, "
                        "record it when an Ada binary is available and none exists")
    p.add_argument("--record-golden", action="store_true",
                   help="force a live Ada run and (over)write the golden file")
    p.add_argument("--allow-stale", action="store_true",
                   help="accept golden files whose scenario fingerprint changed")
    p.add_argument("--compare-files", nargs=2, metavar=("ADA_JSON", "CPP_JSON"),
                   help="compare two raw capture files instead of running binaries "
                        "(needs --scenario for normalisation/comparators)")
    p.add_argument("--save-captures", metavar="DIR",
                   help="write raw captures (ada.json / cpp.json) to DIR")
    p.add_argument("--report", metavar="FILE", help="also write the JSON report")
    p.add_argument("--plugin", action="append", default=[], metavar="MOD_OR_PY",
                   help="load a comparator plug-in (module or .py file); repeatable")
    p.add_argument("--list-comparators", action="store_true")
    p.add_argument("--log-dir", metavar="DIR", help="store stdout of started binaries")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def selftest():
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(HERE, "tests"), top_level_dir=os.path.dirname(HERE))
    res = unittest.TextTestRunner(verbosity=1).run(suite)
    return EXIT_MATCH if res.wasSuccessful() else EXIT_DIFF


def _load_raw(path):
    with open(path) as fd:
        d = json.load(fd)
    return d["messages"] if isinstance(d, dict) else d


def main(argv=None, launcher=None, transport_factory=None, out=None):
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    if args.selftest:
        return selftest()
    try:
        for plug in args.plugin:
            comparators.load_plugin(plug)
        if args.list_comparators:
            out.write("\n".join(comparators.names()) + "\n")
            return EXIT_MATCH
        if not args.scenario:
            build_parser().print_usage(sys.stderr)
            sys.stderr.write("error: --scenario (or --selftest) is required\n")
            return EXIT_USAGE
        sc = scenario.load(args.scenario)
    except (scenario.ScenarioError, comparators.ComparatorError) as e:
        sys.stderr.write("error: %s\n" % e)
        return EXIT_USAGE

    launcher = launcher or runner.default_launcher(args.log_dir)
    transport_factory = transport_factory or runner.default_transport_factory
    notes = []
    try:
        if args.compare_files:
            ada_raw, cpp_raw = (_load_raw(f) for f in args.compare_files)
            notes.append("compared pre-recorded capture files")
        else:
            ada_raw, notes = runner.obtain_ada(
                sc, args.ada_bin, args.cpp_bin, args.golden, args.record_golden,
                args.allow_stale, launcher, transport_factory)
            if not args.cpp_bin:
                if args.record_golden:
                    out.write("\n".join(notes) + "\nRecorded; no --cpp-bin so no comparison.\n")
                    return EXIT_MATCH
                sys.stderr.write("error: --cpp-bin is required for comparison\n")
                return EXIT_USAGE
            cpp_raw = runner.run_side(sc, "cpp", args.cpp_bin, launcher, transport_factory)
        if args.save_captures:
            os.makedirs(args.save_captures, exist_ok=True)
            for n, d in (("ada", ada_raw), ("cpp", cpp_raw)):
                with open(os.path.join(args.save_captures, n + ".json"), "w") as fd:
                    json.dump({"messages": d}, fd, indent=1)
        rep = runner.compare(sc, ada_raw, cpp_raw, notes)
    except golden.GoldenError as e:
        sys.stderr.write("error: %s\n" % e)
        return EXIT_GOLDEN
    except comparators.ComparatorError as e:
        sys.stderr.write("error: %s\n" % e)
        return EXIT_USAGE
    except (runner.RunError, OSError, ValueError, KeyError) as e:
        sys.stderr.write("infrastructure error: %s\n" % e)
        return EXIT_INFRA
    except Exception as e:
        from .live import LiveError
        if isinstance(e, LiveError):
            sys.stderr.write("infrastructure error: %s\n" % e)
            return EXIT_INFRA
        raise
    out.write(rep.render())
    if args.report:
        with open(args.report, "w") as fd:
            fd.write(rep.to_json() + "\n")
    return EXIT_MATCH if rep.ok else EXIT_DIFF
