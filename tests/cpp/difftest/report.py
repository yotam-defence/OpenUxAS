"""Diff report rendering."""
import json
from typing import List

from difftest.comparators import ComparisonResult


def total_differences(results: List[ComparisonResult]) -> int:
    return sum(len(r.differences) for r in results)


def render_text(scenario_name, results: List[ComparisonResult],
                ref_label="ada", cand_label="cpp", max_detail=200) -> str:
    n = total_differences(results)
    lines = ["Differential run: %s (reference=%s, candidate=%s)"
             % (scenario_name, ref_label, cand_label)]
    for r in results:
        lines.append("  [%s] service=%s reference=%d candidate=%d differences=%d"
                     % (r.comparator, r.service, r.ref_count, r.cand_count,
                        len(r.differences)))
    shown = 0
    for r in results:
        for d in r.differences:
            if shown >= max_detail:
                break
            shown += 1
            lines.append("  - step %d %s %s: %s" % (d.step, d.kind, d.type, d.detail))
    if n > shown:
        lines.append("  ... %d more differences not shown" % (n - shown))
    lines.append("RESULT: %s" % ("MATCH" if n == 0 else "DIFFER (%d)" % n))
    return "\n".join(lines)


def render_json(scenario_name, results: List[ComparisonResult],
                ref_label="ada", cand_label="cpp") -> str:
    return json.dumps({
        "scenario": scenario_name, "reference": ref_label,
        "candidate": cand_label, "match": total_differences(results) == 0,
        "results": [{"comparator": r.comparator, "service": r.service,
                     "ref_count": r.ref_count, "cand_count": r.cand_count,
                     "differences": [d.as_dict() for d in r.differences]}
                    for r in results]}, indent=2, sort_keys=True)
