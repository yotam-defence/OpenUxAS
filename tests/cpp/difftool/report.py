"""Diff results and report rendering."""
import json

MISSING_IN_CPP = "missing_in_cpp"   # Ada produced it, C++ did not
EXTRA_IN_CPP = "extra_in_cpp"       # C++ produced it, Ada did not
MISMATCH = "mismatch"               # same slot, different content
COUNT = "count"


class Difference(object):
    def __init__(self, kind, message, window=None, type_name=None,
                 ada=None, cpp=None, path=None, comparator=None):
        self.kind = kind
        self.message = message
        self.window = window
        self.type = type_name
        self.ada = ada
        self.cpp = cpp
        self.path = path
        self.comparator = comparator

    def as_dict(self):
        return {"kind": self.kind, "message": self.message,
                "window": self.window, "type": self.type, "path": self.path,
                "ada": self.ada, "cpp": self.cpp, "comparator": self.comparator}


def diff_values(a, b, path=""):
    """Yield ``(path, a_value, b_value)`` for every leaf difference."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = "%s.%s" % (path, k) if path else k
            if k not in a:
                yield (p, "<absent>", b[k])
            elif k not in b:
                yield (p, a[k], "<absent>")
            else:
                for d in diff_values(a[k], b[k], p):
                    yield d
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield (path + "[]", "len=%d" % len(a), "len=%d" % len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            for d in diff_values(x, y, "%s[%d]" % (path, i)):
                yield d
    elif a != b:
        yield (path, a, b)


class Report(object):
    """Aggregated result of running all comparators on one scenario."""

    def __init__(self, scenario, differences=None, stats=None, notes=None):
        self.scenario = scenario
        self.differences = list(differences or [])
        self.stats = dict(stats or {})
        self.notes = list(notes or [])

    @property
    def ok(self):
        return not self.differences

    def as_dict(self):
        return {"scenario": self.scenario, "ok": self.ok, "stats": self.stats,
                "notes": self.notes,
                "differences": [d.as_dict() for d in self.differences]}

    def to_json(self):
        return json.dumps(self.as_dict(), indent=2, sort_keys=True, default=str)

    def render(self, max_diffs=50):
        lines = ["Scenario: %s" % self.scenario]
        for k in sorted(self.stats):
            lines.append("  %s: %s" % (k, self.stats[k]))
        for n in self.notes:
            lines.append("  note: %s" % n)
        if self.ok:
            lines.append("RESULT: MATCH")
            return "\n".join(lines) + "\n"
        lines.append("RESULT: DIFFERENT (%d difference%s)" % (
            len(self.differences), "" if len(self.differences) == 1 else "s"))
        for i, d in enumerate(self.differences[:max_diffs], 1):
            where = "window %s" % d.window if d.window is not None else "stream"
            lines.append("%d. [%s] %s (%s, comparator=%s)" % (
                i, d.kind, d.message, where, d.comparator))
            if d.path is not None:
                lines.append("     path: %s" % d.path)
            if d.kind in (MISMATCH,):
                lines.append("     ada: %s" % json.dumps(d.ada, sort_keys=True, default=str))
                lines.append("     cpp: %s" % json.dumps(d.cpp, sort_keys=True, default=str))
            elif d.kind == MISSING_IN_CPP:
                lines.append("     ada: %s" % json.dumps(d.ada, sort_keys=True, default=str))
            elif d.kind == EXTRA_IN_CPP:
                lines.append("     cpp: %s" % json.dumps(d.cpp, sort_keys=True, default=str))
        if len(self.differences) > max_diffs:
            lines.append("... %d more not shown" % (len(self.differences) - max_diffs))
        return "\n".join(lines) + "\n"
