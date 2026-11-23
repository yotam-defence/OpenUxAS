"""Command line interface (``tests/cpp/run-diff``)."""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
import time
from typing import List, Optional

from .capture import Capture, GoldenError
from .config import build_config
from .differ import dump_canonical
from .runner import RunContext, RunError, run_scenario
from .process import ProcessError
from .scenario import ScenarioError, load_scenario

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCENARIO_DIR = os.path.join(HERE, "scenarios")
DEFAULT_GOLDEN_DIR = os.path.join(HERE, "golden")

EXIT_OK, EXIT_DIFF, EXIT_USAGE, EXIT_INFRA = 0, 1, 2, 3
SUBCOMMANDS = ("run", "gen-config", "record", "show")


def _resolve_scenarios(args: List[str], all_: bool, directory: str
                       ) -> List[str]:
    paths = []
    for a in args:
        if os.path.isfile(a):
            paths.append(a)
        elif os.path.isfile(os.path.join(directory, a + ".json")):
            paths.append(os.path.join(directory, a + ".json"))
        elif os.path.isfile(os.path.join(directory, a)):
            paths.append(os.path.join(directory, a))
        else:
            raise ScenarioError("scenario not found: %s" % a)
    if all_:
        paths += sorted(glob.glob(os.path.join(directory, "*.json")))
    if not paths:
        raise ScenarioError("no scenario given (name, path or --all)")
    return paths


def _binary(explicit: Optional[str], env: str, name: str) -> Optional[str]:
    return explicit or os.environ.get(env) or shutil.which(name)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run-diff",
        description="Differential replay harness: Ada uxas_ada vs C++ uxas")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="replay scenarios and diff (default)")
    r.add_argument("scenarios", nargs="*",
                   help="scenario file or name in the scenario dir")
    r.add_argument("--all", action="store_true",
                   help="run every scenario of the scenario dir")
    r.add_argument("--scenario-dir", default=DEFAULT_SCENARIO_DIR)
    r.add_argument("--uxas", help="C++ uxas binary (env UXAS_BIN, PATH)")
    r.add_argument("--uxas-ada", help="Ada binary (env UXAS_ADA_BIN, PATH)")
    r.add_argument("--golden-dir", default=DEFAULT_GOLDEN_DIR,
                   help="golden capture directory (default: %(default)s)")
    r.add_argument("--ada", choices=("auto", "live", "golden"),
                   default="auto", help="source of the reference output: "
                   "auto = fresh golden file if present else live run")
    r.add_argument("--cpp", choices=("auto", "live", "golden"),
                   default="live")
    r.add_argument("--update-golden", action="store_true",
                   help="run live and (re)write golden captures")
    r.add_argument("--allow-stale-golden", action="store_true")
    r.add_argument("--workdir", help="keep run files (configs, logs) here")
    r.add_argument("--report", help="write a JSON report to this file")
    r.add_argument("-v", "--verbose", action="store_true")

    g = sub.add_parser("gen-config", help="print the generated XML config")
    g.add_argument("scenario")
    g.add_argument("side", choices=("ada", "cpp"))
    g.add_argument("--scenario-dir", default=DEFAULT_SCENARIO_DIR)

    rec = sub.add_parser("record", help="record a bus into a JSONL file "
                         "usable as a scenario 'recording'")
    rec.add_argument("output")
    rec.add_argument("--sub-url", default="tcp://127.0.0.1:5560")
    rec.add_argument("--duration", type=float, default=10.0,
                     help="seconds to record")

    s = sub.add_parser("show", help="print canonical form of a golden "
                       "file")
    s.add_argument("golden_file")
    return p


def cmd_run(a) -> int:
    try:
        paths = _resolve_scenarios(a.scenarios, a.all, a.scenario_dir)
        scenarios = [load_scenario(p) for p in paths]
    except ScenarioError as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    ctx = RunContext(
        binaries={"cpp": _binary(a.uxas, "UXAS_BIN", "uxas"),
                  "ada": _binary(a.uxas_ada, "UXAS_ADA_BIN", "uxas_ada")},
        workdir=a.workdir, keep_workdir=bool(a.workdir),
        log=(lambda s: print(s, file=sys.stderr)) if a.verbose
        else (lambda s: None))
    worst, reports = EXIT_OK, []
    for sc in scenarios:
        try:
            res = run_scenario(sc, ctx, ada=a.ada, cpp=a.cpp,
                               golden_dir=a.golden_dir,
                               update_golden=a.update_golden,
                               allow_stale=a.allow_stale_golden)
        except (RunError, ProcessError, GoldenError) as e:
            print("scenario %s: ERROR: %s" % (sc.name, e), file=sys.stderr)
            worst = max(worst, EXIT_INFRA)
            reports.append({"scenario": sc.name, "error": str(e)})
            continue
        print(res.format())
        reports.append(res.to_dict())
        if not res.ok:
            worst = max(worst, EXIT_DIFF)
    if a.report:
        with open(a.report, "w") as fd:
            json.dump(reports, fd, indent=1)
    return worst


def cmd_gen_config(a) -> int:
    try:
        sc = load_scenario(_resolve_scenarios([a.scenario], False,
                                              a.scenario_dir)[0])
    except ScenarioError as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    sys.stdout.write(build_config(sc, a.side).decode("utf-8"))
    return EXIT_OK


def cmd_record(a) -> int:
    from .bus import ClientBus
    bus = ClientBus(a.sub_url, a.sub_url)   # push socket unused
    bus.open()
    last = time.monotonic()
    end = last + a.duration
    n = 0
    try:
        with open(a.output, "w") as fd:
            fd.write("# run-diff recording: one JSON object per line\n")
            while time.monotonic() < end:
                for f in bus.poll():
                    now = time.monotonic()
                    fd.write(json.dumps({
                        "delay_ms": int((now - last) * 1000),
                        "frame_hex": f.hex()}) + "\n")
                    last = now
                    n += 1
                time.sleep(0.01)
    finally:
        bus.close()
    print("recorded %d frame(s) to %s" % (n, a.output))
    return EXIT_OK


def cmd_show(a) -> int:
    try:
        with open(a.golden_file) as fd:
            cap = Capture.from_dict(json.load(fd))
    except (OSError, ValueError, GoldenError) as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    print(dump_canonical(cap.decode()))
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in SUBCOMMANDS and
                    argv[0] not in ("-h", "--help")):
        argv.insert(0, "run")
    a = build_parser().parse_args(argv)
    return {"run": cmd_run, "gen-config": cmd_gen_config,
            "record": cmd_record, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
