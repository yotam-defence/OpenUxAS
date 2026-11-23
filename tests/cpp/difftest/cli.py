"""Command line: ``python3 -m difftest {run,compare,canon,list-comparators}``."""
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from difftest import __version__, comparators, golden, scenario as scn
from difftest.canon import CanonConfig, canonicalise, filter_capture
from difftest.report import compare

EXIT_OK, EXIT_DIFF, EXIT_ERROR = 0, 1, 2

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GOLDEN_DIR = os.path.join(HERE, "scenarios", "golden")


def _canon(sc: scn.Scenario, capture: List[Dict[str, Any]]):
    filtered = filter_capture(capture, sc.capture.include_descriptors,
                              sc.capture.exclude_descriptors)
    return canonicalise(filtered, CanonConfig.from_dict(sc.canonical))


def _obtain(sc, side, args, log):
    """Get the raw capture for one side: golden file or live run."""
    use_golden = getattr(args, side + "_golden")
    gdir = args.golden_dir
    gpath = golden.golden_path(gdir, sc.name, side)
    if use_golden:
        log("%s: using golden %s" % (side, gpath))
        return golden.load(gpath, sc.name)
    from difftest import runner
    exe = runner.find_binary(side, getattr(args, side + "_bin"))
    if exe is None:
        raise runner.RunnerError(
            "%s binary not found; pass --%s-bin, set UXAS_%s_BIN, or use "
            "--%s-golden" % (side, side, side.upper(), side))
    extra = (args.ada_args if side == "ada" else args.cpp_args) or []
    capture = runner.run_binary(sc, side, exe, extra_args=extra,
                                pub=args.pub, pull=args.pull, log=log)
    if args.record_golden:
        golden.save(gpath, sc.name, side, capture)
        log("%s: recorded golden %s" % (side, gpath))
    return capture


def cmd_run(args) -> int:
    log = (lambda s: print("[difftest] " + s, file=sys.stderr))
    try:
        sc = scn.load(args.scenario)
        for p in list(sc.plugins) + list(args.plugin or []):
            comparators.load_plugin(p)
        ada = _obtain(sc, "ada", args, log)
        cpp = _obtain(sc, "cpp", args, log)
        report = compare(_canon(sc, ada), _canon(sc, cpp),
                         sc.comparators, sc.name)
    except Exception as e:  # scenario/golden/runner/comparator errors
        print("difftest: error: %s" % e, file=sys.stderr)
        return EXIT_ERROR
    print(report.to_json() if args.format == "json" else report.to_text())
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fd:
            fd.write(report.to_json() + "\n")
    return EXIT_OK if report.passed else EXIT_DIFF


def cmd_compare(args) -> int:
    """Compare two golden/capture files offline."""
    try:
        sc = scn.load(args.scenario) if args.scenario else \
            scn.Scenario(name="adhoc")
        for p in list(sc.plugins) + list(args.plugin or []):
            comparators.load_plugin(p)
        ada = golden.load(args.ada)
        cpp = golden.load(args.cpp)
        report = compare(_canon(sc, ada), _canon(sc, cpp),
                         sc.comparators, sc.name)
    except Exception as e:
        print("difftest: error: %s" % e, file=sys.stderr)
        return EXIT_ERROR
    print(report.to_json() if args.format == "json" else report.to_text())
    return EXIT_OK if report.passed else EXIT_DIFF


def cmd_canon(args) -> int:
    try:
        sc = scn.load(args.scenario) if args.scenario else \
            scn.Scenario(name="adhoc")
        print(json.dumps(_canon(sc, golden.load(args.capture)), indent=2,
                         sort_keys=True))
    except Exception as e:
        print("difftest: error: %s" % e, file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def cmd_list(args) -> int:
    for n in comparators.available():
        print(n)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="difftest",
        description="Ada-vs-C++ differential replay harness for UxAS")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a scenario against both binaries")
    r.add_argument("scenario")
    r.add_argument("--ada-bin")
    r.add_argument("--cpp-bin")
    r.add_argument("--ada-args", nargs="*",
                   help="extra arguments for the Ada binary")
    r.add_argument("--cpp-args", nargs="*",
                   help="extra arguments for the C++ binary")
    r.add_argument("--ada-golden", action="store_true",
                   help="use the cached Ada capture instead of running Ada")
    r.add_argument("--cpp-golden", action="store_true",
                   help="use the cached C++ capture instead of running C++")
    r.add_argument("--record-golden", action="store_true",
                   help="store the capture of every live run as golden")
    r.add_argument("--golden-dir", default=DEFAULT_GOLDEN_DIR)
    r.add_argument("--pub", default="tcp://127.0.0.1:5560")
    r.add_argument("--pull", default="tcp://127.0.0.1:5561")
    r.add_argument("--plugin", action="append",
                   help="python module registering comparators")
    r.add_argument("--format", choices=("text", "json"), default="text")
    r.add_argument("--report", help="also write a JSON report here")
    r.set_defaults(fn=cmd_run)

    c = sub.add_parser("compare", help="compare two capture/golden files")
    c.add_argument("ada")
    c.add_argument("cpp")
    c.add_argument("--scenario")
    c.add_argument("--plugin", action="append")
    c.add_argument("--format", choices=("text", "json"), default="text")
    c.set_defaults(fn=cmd_compare)

    k = sub.add_parser("canon", help="print the canonical form of a capture")
    k.add_argument("capture")
    k.add_argument("--scenario")
    k.set_defaults(fn=cmd_canon)

    l = sub.add_parser("list-comparators")
    l.set_defaults(fn=cmd_list)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)
