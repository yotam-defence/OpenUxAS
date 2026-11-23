"""Diff two normalised captures using a ComparatorSet."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .canonical import CanonMessage, CanonSettings, canonicalise
from .comparators import ComparatorSet, Difference
from .messages import DecodedMessage


@dataclass
class DiffResult:
    scenario: str
    differences: List[Difference] = field(default_factory=list)
    ref_count: int = 0
    got_count: int = 0
    windows: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.differences

    def to_dict(self) -> Dict:
        return {"scenario": self.scenario, "ok": self.ok,
                "reference_messages": self.ref_count,
                "candidate_messages": self.got_count,
                "windows": self.windows, "notes": self.notes,
                "differences": [vars(d) for d in self.differences]}

    def format(self) -> str:
        lines = ["scenario %s: %s (reference=%d candidate=%d messages, "
                 "%d window(s))" % (self.scenario,
                                    "MATCH" if self.ok else "MISMATCH",
                                    self.ref_count, self.got_count,
                                    self.windows)]
        lines += ["  note: " + n for n in self.notes]
        for d in self.differences:
            lines.append("  [window %d] %s %s: %s" % (d.window, d.kind,
                                                      d.type, d.detail))
            if d.ref:
                lines.append("    - " + d.ref)
            if d.got:
                lines.append("    + " + d.got)
        return "\n".join(lines)


def diff_messages(scenario_name: str, ref: List[DecodedMessage],
                  got: List[DecodedMessage], comparators: ComparatorSet,
                  settings: Optional[CanonSettings] = None,
                  exclude_types: Optional[List[str]] = None) -> DiffResult:
    """Canonicalise both message lists and compare window by window."""
    excl = set(exclude_types or [])
    ref = [m for m in ref if m.type not in excl]
    got = [m for m in got if m.type not in excl]
    cr = canonicalise(ref, settings)
    cg = canonicalise(got, settings)
    result = DiffResult(scenario_name, ref_count=len(ref),
                        got_count=len(got))
    windows = sorted(set(cr) | set(cg))
    result.windows = len(windows)
    for w in windows:
        groups_r: Dict[int, List[CanonMessage]] = defaultdict(list)
        groups_g: Dict[int, List[CanonMessage]] = defaultdict(list)
        comps = {}
        for m in cr.get(w, []):
            c = comparators.select(m.type)
            comps[id(c)] = c
            groups_r[id(c)].append(m)
        for m in cg.get(w, []):
            c = comparators.select(m.type)
            comps[id(c)] = c
            groups_g[id(c)].append(m)
        for cid, comp in comps.items():
            result.differences.extend(
                comp.compare(w, groups_r[cid], groups_g[cid]))
    return result


def dump_canonical(messages: List[DecodedMessage],
                   settings: Optional[CanonSettings] = None) -> str:
    """Human readable canonical form (used by the ``show`` sub-command)."""
    out = []
    for w, msgs in canonicalise(messages, settings).items():
        out.append("window %d:" % w)
        for m in msgs:
            out.append("  " + m.key)
    return "\n".join(out)
