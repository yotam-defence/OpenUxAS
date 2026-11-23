"""Scenario execution, golden files and the differential driver."""

import json
import os
import tempfile

from . import comparators, normalise
from .backends import RunError, ZmqProcessBackend

GOLDEN_FORMAT = 1

# Exit codes of run_differential.py
EXIT_MATCH = 0
EXIT_DIFF = 1
EXIT_USAGE = 2
EXIT_RUN_FAILURE = 3
EXIT_GOLDEN = 4


class SideResult(object):
    def __init__(self, side):
        self.side = side
        self.captured = []      # list[normalise.Captured]
        self.records = []       # canonical records
        self.return_codes = {}
        self.error = None       # RunError or None
        self.from_golden = False

    @property
    def ok(self):
        return self.error is None


def run_side(scenario, backend, sleep_hook=None):
    """Drive ``backend`` through ``scenario``; returns a :class:`SideResult`.

    Deterministic schedule: start (+startup settle done by backend), then for
    each step wait ``delay_ms`` and send, finally wait ``post_replay_settle_ms``.
    Captured messages are tagged with the number of the last replayed step.
    """
    res = SideResult(backend.side)
    step_no = 0
    try:
        backend.start()
        for step in scenario.replay:
            backend.wait(step.delay_ms)
            res.captured.extend(_tag(backend.drain(), step_no))
            backend.check()
            backend.send(step.envelope)
            step_no = step.index + 1
        backend.wait(scenario.timing["post_replay_settle_ms"])
        backend.check()
        res.captured.extend(_tag(backend.drain(), step_no))
    except RunError as exc:
        res.error = exc
    finally:
        try:
            res.captured.extend(_tag(backend.drain(), step_no))
        except Exception:
            pass
        res.return_codes = backend.stop() or {}
    if res.error is None:
        # A process that did not exit cleanly on shutdown is reported.
        bad = {k: v for k, v in res.return_codes.items()
               if isinstance(v, dict) and not v.get("clean", True)}
        if bad:
            res.error = RunError("unclean exit: %s" % json.dumps(bad, sort_keys=True),
                                 "crash")
    return res


def _tag(items, step_no):
    return [normalise.Captured(raw, t, step_no) for raw, t in items]


def normaliser_for(scenario):
    # echo suppression compares LMCP frames (payloads) byte for byte
    payloads = ([s.envelope.payload for s in scenario.replay]
                if scenario.exclude_echo else [])
    return normalise.Normaliser.from_options(scenario.normalise_options,
                                             exclude_raw=payloads)


def finish(scenario, res):
    res.records = normaliser_for(scenario).normalise(res.captured)
    return res


# -- golden files ------------------------------------------------------------

class GoldenError(Exception):
    pass


def write_golden(path, scenario, res):
    doc = {"format": GOLDEN_FORMAT, "scenario": scenario.name,
           "scenario_digest": scenario.digest(), "side": res.side,
           "records": res.records}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fd:
        json.dump(doc, fd, indent=2, sort_keys=True)
        fd.write("\n")
    os.replace(tmp, path)


def read_golden(path, scenario, check_digest=True):
    try:
        with open(path, "r", encoding="utf-8") as fd:
            doc = json.load(fd)
    except (OSError, ValueError) as exc:
        raise GoldenError("cannot read golden %s: %s" % (path, exc))
    if doc.get("format") != GOLDEN_FORMAT or "records" not in doc:
        raise GoldenError("%s is not a format-%d golden file" %
                          (path, GOLDEN_FORMAT))
    if doc.get("scenario") != scenario.name:
        raise GoldenError("golden is for scenario %r, not %r" %
                          (doc.get("scenario"), scenario.name))
    if check_digest and doc.get("scenario_digest") != scenario.digest():
        raise GoldenError("golden is stale: scenario changed since it was "
                          "recorded (re-record or pass --ignore-golden-digest)")
    return doc


# -- driver ------------------------------------------------------------------

class DifferentialResult(object):
    def __init__(self):
        self.exit_code = EXIT_MATCH
        self.report = None
        self.sides = {}
        self.messages = []

    def as_dict(self):
        return {
            "exit_code": self.exit_code,
            "messages": self.messages,
            "report": self.report.as_dict() if self.report else None,
            "sides": {k: {"records": len(v.records),
                          "return_codes": v.return_codes,
                          "from_golden": v.from_golden,
                          "error": str(v.error) if v.error else None}
                      for k, v in self.sides.items()}}


def run_differential(scenario, backend_factory, golden=None,
                     record_golden=None, golden_side="ada",
                     ignore_golden_digest=False, ref_side="ada",
                     cand_side="cpp", record_only=False):
    """Run the differential for ``scenario``.

    :param backend_factory: ``f(side) -> Backend``
    :param golden: path of a golden file used instead of running ``ref_side``
    :param record_golden: path to write the ``golden_side`` output to; the
        recorded run is reused for the comparison unless ``record_only``
    """
    out = DifferentialResult()
    comp = comparators.get_comparator(scenario.comparator,
                                      scenario.comparator_options)

    def run(side):
        res = finish(scenario, run_side(scenario, backend_factory(side)))
        out.sides[side] = res
        if res.error:
            out.messages.append("%s: %s: %s" % (side, res.error.kind, res.error))
        return res

    if record_golden:
        res = run(golden_side)
        if not res.ok:
            out.exit_code = EXIT_RUN_FAILURE
            return out
        write_golden(record_golden, scenario, res)
        out.messages.append("recorded %d records from %s to %s" %
                            (len(res.records), golden_side, record_golden))
        if record_only:
            return out

    if golden:
        try:
            doc = read_golden(golden, scenario, not ignore_golden_digest)
        except GoldenError as exc:
            out.messages.append(str(exc))
            out.exit_code = EXIT_GOLDEN
            return out
        ref = SideResult(doc.get("side", ref_side))
        ref.records, ref.from_golden = doc["records"], True
        out.sides[ref_side] = ref
    else:
        ref = out.sides.get(ref_side) or run(ref_side)
    cand = out.sides.get(cand_side) or run(cand_side)
    if not (ref.ok and cand.ok):
        out.exit_code = EXIT_RUN_FAILURE
        return out
    out.report = comp.compare(ref.records, cand.records)
    out.exit_code = EXIT_MATCH if out.report.equal else EXIT_DIFF
    return out


def real_backend_factory(scenario, workdir, cpp_bin=None, ada_bin=None):
    def factory(side):
        return ZmqProcessBackend(scenario, side, workdir, uxas_bin=cpp_bin,
                                 ada_bin=ada_bin)
    return factory


def make_workdir(keep=None):
    if keep:
        os.makedirs(keep, exist_ok=True)
        return keep, False
    return tempfile.mkdtemp(prefix="uxdiff-"), True
