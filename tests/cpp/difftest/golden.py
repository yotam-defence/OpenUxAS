"""Golden-file cache of raw captures (used when a binary is unavailable)."""
import json
import os
from typing import Any, Dict, List, Optional

GOLDEN_VERSION = 1


class GoldenError(Exception):
    pass


def golden_path(golden_dir: str, scenario: str, binary: str) -> str:
    return os.path.join(golden_dir, "%s.%s.json" % (scenario, binary))


def save(path: str, scenario: str, binary: str,
         messages: List[Dict[str, Any]], provenance: str = "recorded") -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    doc = {"version": GOLDEN_VERSION, "scenario": scenario, "binary": binary,
           "provenance": provenance, "messages": messages}
    with open(path, "w", encoding="utf-8") as fd:
        json.dump(doc, fd, indent=2, sort_keys=True)
        fd.write("\n")


def load(path: str, scenario: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fd:
            doc = json.load(fd)
    except OSError as e:
        raise GoldenError("golden file unavailable: %s (record it with "
                          "--record-golden): %s" % (path, e))
    except ValueError as e:
        raise GoldenError("invalid golden file %s: %s" % (path, e))
    if doc.get("version") != GOLDEN_VERSION:
        raise GoldenError("%s: unsupported golden version %r" %
                          (path, doc.get("version")))
    if scenario is not None and doc.get("scenario") != scenario:
        raise GoldenError("%s: golden is for scenario %r, not %r" %
                          (path, doc.get("scenario"), scenario))
    return list(doc.get("messages", []))
