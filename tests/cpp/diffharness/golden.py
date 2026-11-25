"""Golden (cached) captures.

Layout: ``<golden_dir>/<scenario name>/<impl>.json`` holding the *decoded,
not yet normalised* records so that normaliser changes never require
re-recording.
"""
import json
import os
from typing import Any, Dict, List

from diffharness.scenario import IMPLS

FORMAT = 1


class GoldenError(Exception):
    pass


def golden_path(golden_dir: str, scenario: str, impl: str) -> str:
    return os.path.join(golden_dir, scenario, impl + ".json")


def save_golden(golden_dir: str, scenario: str, impl: str,
                records: List[Dict[str, Any]],
                provenance: str = "recorded") -> str:
    if impl not in IMPLS:
        raise ValueError(impl)
    path = golden_path(golden_dir, scenario, impl)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fd:
        json.dump({"format": FORMAT, "scenario": scenario, "impl": impl,
                   "provenance": provenance, "records": records},
                  fd, indent=2, sort_keys=True)
        fd.write("\n")
    return path


def load_golden(golden_dir: str, scenario: str, impl: str
                ) -> List[Dict[str, Any]]:
    path = golden_path(golden_dir, scenario, impl)
    if not os.path.isfile(path):
        raise GoldenError(
            "no golden file %s; record one with --update-golden against a "
            "real %s binary" % (path, impl))
    with open(path, encoding="utf-8") as fd:
        data = json.load(fd)
    if data.get("format") != FORMAT:
        raise GoldenError("%s: unsupported golden format" % path)
    return data["records"]
