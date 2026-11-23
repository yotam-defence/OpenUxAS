"""Compare two canonical captures and render a report."""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from difftest import comparators


@dataclass
class Report:
    scenario: str
    ada_count: int
    cpp_count: int
    diffs: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.diffs

    def to_dict(self) -> Dict[str, Any]:
        return {"scenario": self.scenario, "passed": self.passed,
                "ada_count": self.ada_count, "cpp_count": self.cpp_count,
                "diffs": self.diffs}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_text(self) -> str:
        lines = ["scenario %s: ada=%d msgs, cpp=%d msgs -> %s" %
                 (self.scenario, self.ada_count, self.cpp_count,
                  "MATCH" if self.passed else "DIFFERENT")]
        for desc in sorted(self.diffs):
            lines.append("  %s:" % desc)
            lines.extend("    - " + d for d in self.diffs[desc])
        return "\n".join(lines)


def compare(ada: List[Dict[str, Any]], cpp: List[Dict[str, Any]],
            comparator_spec: Optional[Dict[str, Any]] = None,
            scenario: str = "") -> Report:
    """Compare two *canonical* captures, descriptor by descriptor."""
    by_desc_a: Dict[str, List[Dict[str, Any]]] = {}
    by_desc_c: Dict[str, List[Dict[str, Any]]] = {}
    for m in ada:
        by_desc_a.setdefault(m["descriptor"], []).append(m)
    for m in cpp:
        by_desc_c.setdefault(m["descriptor"], []).append(m)
    report = Report(scenario, len(ada), len(cpp))
    for desc in sorted(set(by_desc_a) | set(by_desc_c)):
        fn, params = comparators.resolve(desc, comparator_spec)
        diffs = fn(by_desc_a.get(desc, []), by_desc_c.get(desc, []), params)
        if diffs:
            report.diffs[desc] = list(diffs)
    return report
