"""Unified diff of rendered outputs."""
import difflib
from typing import List


def unified_diff(expected: List[str], actual: List[str],
                 expected_label: str = "ada", actual_label: str = "cpp",
                 context: int = 3) -> str:
    return "".join(
        l if l.endswith("\n") else l + "\n"
        for l in difflib.unified_diff(
            expected, actual, fromfile=expected_label, tofile=actual_label,
            n=context, lineterm=""))
