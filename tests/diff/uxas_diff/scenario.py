"""Scenario loading and validation.

A scenario is a directory holding ``scenario.json`` plus the XML configs it
references (see README.md for the full format).
"""
import json
import os
from typing import Any, Dict, List

DIFF_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO_DIR = os.path.join(DIFF_ROOT, "scenarios")
GOLDEN_DIR = os.path.join(DIFF_ROOT, "golden")


class ScenarioError(Exception):
    pass


def resolve(name_or_path: str) -> str:
    """Return the scenario directory for a name or a path."""
    cands = [name_or_path, os.path.join(SCENARIO_DIR, name_or_path)]
    for c in cands:
        if os.path.isfile(c) and c.endswith(".json"):
            return os.path.dirname(os.path.abspath(c))
        if os.path.isfile(os.path.join(c, "scenario.json")):
            return os.path.abspath(c)
    raise ScenarioError("scenario not found: %s" % name_or_path)


def validate(sc: Dict[str, Any]) -> None:
    for key in ("name", "configs", "messages"):
        if key not in sc:
            raise ScenarioError("scenario missing %r" % key)
    cfgs = sc["configs"]
    if "cpp" not in cfgs or "ada" not in cfgs:
        raise ScenarioError("configs must define both 'ada' and 'cpp'")
    for i, step in enumerate(sc["messages"]):
        kinds = [k for k in ("object", "hex") if k in step]
        if len(kinds) > 1:
            raise ScenarioError("message %d: give only one of object/hex" % i)
        if not kinds and "delay_ms" not in step:
            raise ScenarioError(
                "message %d: needs object, hex or delay_ms" % i)
        if "hex" in step:
            try:
                bytes.fromhex(step["hex"])
            except ValueError as e:
                raise ScenarioError("message %d: bad hex: %s" % (i, e))
        if "object" in step and "class" not in step["object"]:
            raise ScenarioError("message %d: object needs 'class'" % i)


def load(name_or_path: str) -> Dict[str, Any]:
    d = resolve(name_or_path)
    with open(os.path.join(d, "scenario.json")) as fd:
        sc = json.load(fd)
    validate(sc)
    sc["_dir"] = d
    sc.setdefault("startup_settle_ms", 2000)
    sc.setdefault("capture", {})
    sc["capture"].setdefault("tail_ms", 1000)
    sc.setdefault("canon", {})
    sc.setdefault("comparators", {})
    sc.setdefault("plugins", [])
    return sc


def config_path(sc: Dict[str, Any], which: str) -> str:
    rel = sc["configs"].get(which)
    if rel is None:
        raise ScenarioError("scenario has no %r config" % which)
    return os.path.join(sc["_dir"], rel)


def steps(sc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sc["messages"]
