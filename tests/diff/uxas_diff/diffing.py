"""Diff engine and reporter."""
import fnmatch
import json
from typing import Any, Dict, List, Optional

from uxas_diff import comparators
from uxas_diff.canon import canonicalise

DEFAULT_COMPARATOR = "canonical"


class Mismatch:
    def __init__(self, type_: str, comparator: str, lines: List[str]):
        self.type = type_
        self.comparator = comparator
        self.lines = lines

    def as_dict(self):
        return {"type": self.type, "comparator": self.comparator,
                "details": self.lines}


class DiffReport:
    def __init__(self, scenario: str, mismatches: List[Mismatch],
                 ref_count: int, test_count: int):
        self.scenario = scenario
        self.mismatches = mismatches
        self.ref_count = ref_count
        self.test_count = test_count

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def as_dict(self):
        return {"scenario": self.scenario, "ok": self.ok,
                "reference_messages": self.ref_count,
                "test_messages": self.test_count,
                "mismatches": [m.as_dict() for m in self.mismatches]}

    def text(self) -> str:
        head = "scenario %s: %s (ref=%d msgs, test=%d msgs)" % (
            self.scenario, "MATCH" if self.ok else "MISMATCH",
            self.ref_count, self.test_count)
        out = [head]
        for m in self.mismatches:
            out.append("  type %s (comparator %s):" % (m.type, m.comparator))
            out.extend("    " + ln for ln in m.lines)
        return "\n".join(out)


def select_comparator(type_: str, mapping: Dict[str, str]) -> str:
    """Exact match first, then first matching glob in mapping order."""
    if type_ in mapping:
        return mapping[type_]
    for pat, name in mapping.items():
        if fnmatch.fnmatchcase(type_, pat):
            return name
    return DEFAULT_COMPARATOR


def diff_canonical(ref: List[dict], test: List[dict],
                   scenario: Optional[Dict[str, Any]] = None,
                   name: str = "?") -> DiffReport:
    scenario = scenario or {}
    mapping = scenario.get("comparators", {})
    types = sorted({m["type"] for m in ref} | {m["type"] for m in test})
    mismatches = []
    for t in types:
        cname = select_comparator(t, mapping)
        fn = comparators.get(cname)
        lines = fn([m for m in ref if m["type"] == t],
                   [m for m in test if m["type"] == t],
                   {"type": t, "scenario": scenario})
        if lines:
            mismatches.append(Mismatch(t, cname, list(lines)))
    return DiffReport(name, mismatches, len(ref), len(test))


def diff_records(ref_records: List[dict], test_records: List[dict],
                 scenario: Optional[Dict[str, Any]] = None,
                 name: str = "?") -> DiffReport:
    cfg = (scenario or {}).get("canon")
    return diff_canonical(canonicalise(ref_records, cfg),
                          canonicalise(test_records, cfg), scenario, name)


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"
