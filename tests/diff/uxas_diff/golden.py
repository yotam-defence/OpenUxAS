"""Golden-file cache of Ada reference captures."""
import datetime
import json
import os
from typing import Any, Dict, List, Optional

from uxas_diff.scenario import GOLDEN_DIR

FORMAT = 1


class GoldenError(Exception):
    pass


def golden_path(name: str, golden_dir: Optional[str] = None) -> str:
    return os.path.join(golden_dir or GOLDEN_DIR, name + ".json")


def save(name: str, records: List[Dict[str, Any]], impl: str = "ada",
         provenance: str = "recorded",
         golden_dir: Optional[str] = None) -> str:
    path = golden_path(name, golden_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = {"format": FORMAT, "scenario": name, "impl": impl,
           "provenance": provenance,
           "recorded_at": datetime.datetime.now(datetime.timezone.utc)
           .strftime("%Y-%m-%dT%H:%M:%SZ"),
           "messages": records}
    with open(path, "w") as fd:
        json.dump(doc, fd, indent=1, sort_keys=True)
        fd.write("\n")
    return path


def load_file(path: str) -> Dict[str, Any]:
    """Load a golden or raw capture file (a bare list is accepted)."""
    with open(path) as fd:
        doc = json.load(fd)
    if isinstance(doc, list):
        doc = {"format": FORMAT, "messages": doc}
    if "messages" not in doc:
        raise GoldenError("%s: no 'messages' key" % path)
    return doc


def load(name: str, golden_dir: Optional[str] = None) -> Dict[str, Any]:
    path = golden_path(name, golden_dir)
    if not os.path.isfile(path):
        raise GoldenError(
            "no golden for scenario %r at %s; record one with an Ada build: "
            "python3 -m uxas_diff record %s" % (name, path, name))
    return load_file(path)
