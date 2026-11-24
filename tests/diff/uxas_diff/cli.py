"""Command line interface: python3 -m uxas_diff run|canon|diff|record."""
import argparse
import json
import os
import sys
from typing import List, Optional

from uxas_diff import comparators, golden, runner, scenario as scen
from uxas_diff.canon import canonicalise
from uxas_diff.diffing import diff_records, dumps

EXIT_OK, EXIT_MISMATCH, EXIT_ERROR = 0, 1, 2


def _load_plugins(sc, extra: List[str]) -> None:
    for p in list(sc.get("plugins", [])) + list(extra or []):
        # Relative .py plug-ins named by a scenario live in its directory.
        rel = os.path.join(sc.get("_dir", ""), p)
        comparators.load_plugin(rel if p.endswith(".py") and
                                os.path.isfile(rel) else p)


def _write(path: Optional[str], text: str) -> None:
    if path:
        with open(path, "w") as fd:
            fd.write(text)


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--plugin", action="append", default=[],
                   help="comparator plug-in (module name or .py path)")
    p.add_argument("--golden-dir", default=None,
                   help="golden directory (default tests/diff/golden)")


def _add_bins(p: argparse.ArgumentParser) -> None:
    p.add_argument("--uxas-bin", default=None,
                   help="C++ uxas binary (default: $UXAS_BIN or PATH)")
    p.add_argument("--ada-bin", default=None,
                   help="uxas_ada binary (default: $UXAS_ADA_BIN or PATH)")
    p.add_argument("--keep-dir", default=None,
                   help="keep per-implementation work dirs and logs here")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="uxas_diff", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run scenario on C++ (and Ada) and diff")
    r.add_argument("scenario")
    r.add_argument("--golden", action="store_true",
                   help="use cached Ada reference output; only run C++")
    r.add_argument("--report", help="write JSON report here")
    r.add_argument("--save-captures", help="directory to store raw captures")
    _add_bins(r)
    _add_common(r)

    rec = sub.add_parser("record", help="run Ada reference, store golden")
    rec.add_argument("scenario")
    rec.add_argument("--impl", choices=["ada", "cpp"], default="ada")
    _add_bins(rec)
    _add_common(rec)

    c = sub.add_parser("canon", help="print canonical form of a capture")
    c.add_argument("file", help="capture / golden JSON file")
    c.add_argument("--scenario", help="apply this scenario's canon options")
    _add_common(c)

    d = sub.add_parser("diff", help="diff two capture/golden files offline")
    d.add_argument("reference")
    d.add_argument("test")
    d.add_argument("--scenario", help="scenario for canon/comparator options")
    d.add_argument("--report", help="write JSON report here")
    _add_common(d)
    return ap


def _cmd_run(a) -> int:
    sc = scen.load(a.scenario)
    _load_plugins(sc, a.plugin)
    cpp_bin = runner.find_binary("cpp", a.uxas_bin)
    if a.golden:
        ref = golden.load(sc["name"], a.golden_dir)
        if ref.get("provenance") == "synthetic":
            print("warning: golden for %s is synthetic (not recorded from "
                  "Ada); re-record with `record`" % sc["name"],
                  file=sys.stderr)
    else:
        ada_bin = runner.find_binary("ada", a.ada_bin)
        ref = {"messages": runner.run_impl(sc, "ada", ada_bin,
                                           hub_bin=cpp_bin,
                                           keep_dir=_sub(a.keep_dir, "ada"))}
    test = runner.run_impl(sc, "cpp", cpp_bin,
                           keep_dir=_sub(a.keep_dir, "cpp"))
    if a.save_captures:
        os.makedirs(a.save_captures, exist_ok=True)
        for tag, recs in (("ref", ref["messages"]), ("cpp", test)):
            with open(os.path.join(a.save_captures,
                                   "%s.%s.json" % (sc["name"], tag)),
                      "w") as fd:
                fd.write(dumps(recs))
    report = diff_records(ref["messages"], test, sc, sc["name"])
    print(report.text())
    _write(a.report, dumps(report.as_dict()))
    return EXIT_OK if report.ok else EXIT_MISMATCH


def _sub(base, name):
    return os.path.join(base, name) if base else None


def _cmd_record(a) -> int:
    sc = scen.load(a.scenario)
    _load_plugins(sc, a.plugin)
    binary = runner.find_binary(a.impl, a.ada_bin if a.impl == "ada"
                                else a.uxas_bin)
    hub = runner.find_binary("cpp", a.uxas_bin) if a.impl == "ada" else None
    recs = runner.run_impl(sc, a.impl, binary, hub_bin=hub,
                           keep_dir=a.keep_dir)
    path = golden.save(sc["name"], recs, impl=a.impl,
                       golden_dir=a.golden_dir)
    print("recorded %d messages -> %s" % (len(recs), path))
    return EXIT_OK


def _cmd_canon(a) -> int:
    cfg = None
    if a.scenario:
        cfg = scen.load(a.scenario).get("canon")
    doc = golden.load_file(a.file)
    sys.stdout.write(dumps(canonicalise(doc["messages"], cfg)))
    return EXIT_OK


def _cmd_diff(a) -> int:
    sc = scen.load(a.scenario) if a.scenario else {"name": "adhoc"}
    _load_plugins(sc, a.plugin)
    ref = golden.load_file(a.reference)
    test = golden.load_file(a.test)
    report = diff_records(ref["messages"], test["messages"], sc, sc["name"])
    print(report.text())
    _write(a.report, dumps(report.as_dict()))
    return EXIT_OK if report.ok else EXIT_MISMATCH


def main(argv: Optional[List[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return {"run": _cmd_run, "record": _cmd_record, "canon": _cmd_canon,
                "diff": _cmd_diff}[a.cmd](a)
    except (scen.ScenarioError, golden.GoldenError, runner.RunnerError,
            comparators.UnknownComparator, ImportError, OSError,
            json.JSONDecodeError, ValueError) as e:
        print("uxas_diff: error: %s" % e, file=sys.stderr)
        return EXIT_ERROR
