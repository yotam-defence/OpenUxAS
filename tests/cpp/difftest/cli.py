"""``python3 -m difftest`` command line interface."""
import argparse
import os
import sys

from difftest import (EXIT_DIFF, EXIT_INFRA, EXIT_MATCH, EXIT_USAGE,
                      comparators, config, golden, normalise, report, runner)
from difftest.scenario import ScenarioError, load_scenario

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GOLDEN_DIR = os.path.join(HERE, "golden")


def build_parser():
    p = argparse.ArgumentParser(
        prog="python3 -m difftest",
        description="Differential replay of an LMCP scenario against the Ada "
                    "reference (uxas_ada) and the C++ port (uxas).")
    p.add_argument("scenario", nargs="?", help="scenario JSON file")
    p.add_argument("--ada-bin", help="uxas_ada executable (default: "
                   "$UXAS_ADA_BIN or uxas_ada on PATH)")
    p.add_argument("--cpp-bin", help="uxas executable (default: "
                   "$UXAS_CPP_BIN or uxas on PATH)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--record-golden", action="store_true",
                   help="run Ada, store its capture as golden file, then "
                        "compare C++ against it")
    g.add_argument("--use-golden", action="store_true",
                   help="do not run Ada; use the stored golden capture")
    p.add_argument("--bootstrap-from-cpp", action="store_true",
                   help="with --record-golden: record the golden from the C++ "
                        "binary instead of Ada (only when no Ada toolchain is "
                        "available). The golden is marked as a bootstrap "
                        "golden in its metadata; re-record from uxas_ada later")
    p.add_argument("--golden-dir", default=os.environ.get("DIFFTEST_GOLDEN_DIR"),
                   help="golden directory (default: <scenario dir>/golden, "
                        "or difftest/golden)")
    p.add_argument("--allow-stale-golden", action="store_true",
                   help="use a golden file even if the scenario changed")
    p.add_argument("--record-only", action="store_true",
                   help="with --record-golden: do not run C++ / compare")
    p.add_argument("--plugin", action="append", default=[],
                   help="python module registering comparators (repeatable)")
    p.add_argument("--report-json", help="also write the JSON report here")
    p.add_argument("--workdir", help="keep configs/logs in this directory")
    p.add_argument("--time-scale", type=float, default=1.0,
                   help="multiply every settle delay (slow machines/CI)")
    p.add_argument("--pub", help="override bridge PUB address")
    p.add_argument("--pull", help="override bridge PULL address")
    p.add_argument("--dump-config", choices=("ada", "cpp"),
                   help="print the generated XML for one implementation and exit")
    p.add_argument("--list-comparators", action="store_true")
    p.add_argument("--validate", action="store_true",
                   help="only load and validate the scenario")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _capture(impl, binary, sc, args):
    r = runner.Runner(impl, binary, sc, workdir=args.workdir and
                      os.path.join(args.workdir, impl), pub=args.pub,
                      pull=args.pull, keep_workdir=bool(args.workdir),
                      time_scale=args.time_scale)
    if args.workdir:
        os.makedirs(r.workdir, exist_ok=True)
    try:
        recs = r.run()
    finally:
        r.cleanup()
    if args.verbose:
        print("%s: captured %d messages" % (impl, len(recs)), file=sys.stderr)
    return recs


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        for mod in args.plugin:
            comparators.load_plugin(mod)
        if args.list_comparators:
            for n in comparators.names():
                doc = (comparators.get(n).__doc__ or "").strip().splitlines()
                print("%-12s %s" % (n, doc[0] if doc else ""))
            return EXIT_MATCH
        if not args.scenario:
            print("error: scenario required", file=sys.stderr)
            return EXIT_USAGE
        sc = load_scenario(args.scenario)
        for mod in sc.plugins:
            comparators.load_plugin(mod)
        # validate comparator names early
        for spec in sc.comparators:
            comparators.get(spec["name"])
        if args.validate:
            print("scenario %s OK (%d messages)" % (sc.name, len(sc.messages)))
            return EXIT_MATCH
        if args.dump_config:
            sys.stdout.write(config.build_config(
                sc, args.dump_config, args.pub, args.pull).decode())
            return EXIT_MATCH
    except (ScenarioError, comparators.UnknownComparator, ImportError) as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_USAGE

    gdir = args.golden_dir or (os.path.join(os.path.dirname(sc.path), "golden")
                               if sc.path else DEFAULT_GOLDEN_DIR)
    gpath = golden.golden_path(gdir, sc.name, "ada")
    ref_label = "ada"
    try:
        if args.bootstrap_from_cpp and not args.record_golden:
            print("error: --bootstrap-from-cpp requires --record-golden",
                  file=sys.stderr)
            return EXIT_USAGE
        if args.use_golden:
            doc = golden.load_doc(gpath, sc, args.allow_stale_golden)
            ref = doc["records"]
            ref_label = "ada(golden)"
            if doc.get("bootstrap"):
                ref_label = "%s(bootstrap golden)" % doc.get("source_impl")
                print("warning: %s" % doc.get("note", "bootstrap golden"),
                      file=sys.stderr)
        elif args.bootstrap_from_cpp:
            ref = _capture("cpp", runner.resolve_binary("cpp", args.cpp_bin),
                           sc, args)
            golden.save(gpath, sc, "ada", ref, source="cpp")
            print("recorded BOOTSTRAP golden from C++ (not Ada): %s" % gpath,
                  file=sys.stderr)
            if args.record_only:
                return EXIT_MATCH
            ref_label = "cpp(bootstrap golden)"
        else:
            ref = _capture("ada", runner.resolve_binary("ada", args.ada_bin),
                           sc, args)
            if args.record_golden:
                golden.save(gpath, sc, "ada", ref)
                print("recorded golden: %s" % gpath, file=sys.stderr)
                if args.record_only:
                    return EXIT_MATCH
        cand = _capture("cpp", runner.resolve_binary("cpp", args.cpp_bin),
                        sc, args)
    except (golden.GoldenError, runner.InfraError) as e:
        print("infrastructure error: %s" % e, file=sys.stderr)
        return EXIT_INFRA

    return compare_and_report(sc, ref, cand, args.report_json,
                              ref_label)


def compare_and_report(sc, ref, cand, report_json=None, ref_label="ada"):
    nref = normalise.normalise(ref, sc.normalise)
    ncand = normalise.normalise(cand, sc.normalise)
    results = comparators.compare_all(nref, ncand, sc.comparators)
    print(report.render_text(sc.name, results, ref_label, "cpp"))
    if report_json:
        with open(report_json, "w", encoding="utf-8") as fd:
            fd.write(report.render_json(sc.name, results, ref_label, "cpp"))
            fd.write("\n")
    return EXIT_DIFF if report.total_differences(results) else EXIT_MATCH
