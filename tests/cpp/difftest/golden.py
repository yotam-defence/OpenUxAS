"""Golden files: recorded normalised Ada output.

Used when the Ada toolchain/binary is unavailable: the C++ output is compared
to the golden recorded earlier from the Ada reference.  Goldens hold
*normalised* messages, so they are stable text and diff well under git.
"""
import json
import os
from typing import Any, Dict, Optional

from difftest import __version__
from difftest.model import Scenario
from difftest.normalise import NormaliserConfig
from difftest.scenario import scenario_digest

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "goldens")
GOLDEN_FORMAT = 1


class GoldenError(Exception):
    pass


def golden_path(scenario: Scenario, golden_dir: Optional[str] = None) -> str:
    return os.path.join(golden_dir or GOLDEN_DIR, scenario.name + ".json")


def write_golden(scenario: Scenario, cfg: NormaliserConfig,
                 windows: Dict[str, Any], golden_dir: Optional[str] = None,
                 implementation: str = "ada") -> str:
    path = golden_path(scenario, golden_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = {"format": GOLDEN_FORMAT,
           "harness_version": __version__,
           "scenario": scenario.name,
           "scenario_digest": scenario_digest(scenario),
           "implementation": implementation,
           "normalise": cfg.fingerprint(),
           "windows": windows}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fd:
        json.dump(doc, fd, indent=2, sort_keys=True)
        fd.write("\n")
    os.replace(tmp, path)
    return path


def read_golden(scenario: Scenario, cfg: NormaliserConfig,
                golden_dir: Optional[str] = None,
                allow_stale: bool = False) -> Dict[str, Any]:
    """Load golden windows; refuse a stale golden unless ``allow_stale``."""
    path = golden_path(scenario, golden_dir)
    try:
        with open(path, encoding="utf-8") as fd:
            doc = json.load(fd)
    except OSError:
        raise GoldenError(
            "no golden for scenario %r (expected %s); record one with "
            "--mode record-golden on a machine with the Ada binary" %
            (scenario.name, path))
    except ValueError as e:
        raise GoldenError("%s: invalid JSON: %s" % (path, e))
    if doc.get("format") != GOLDEN_FORMAT:
        raise GoldenError("%s: unsupported golden format %r" %
                          (path, doc.get("format")))
    problems = []
    if doc.get("scenario_digest") != scenario_digest(scenario):
        problems.append("scenario changed since the golden was recorded")
    if doc.get("normalise") != cfg.fingerprint():
        problems.append("normaliser configuration changed")
    if problems and not allow_stale:
        raise GoldenError("%s is stale: %s (re-record with --mode "
                          "record-golden or pass --allow-stale)" %
                          (path, "; ".join(problems)))
    return doc["windows"]
