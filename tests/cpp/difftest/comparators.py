"""Per-service comparator plug-in registry (design decision 1, approach 2
layered on top of approach 1).

A comparator is a callable ``fn(ref, cand, options) -> List[Difference]`` where
``ref``/``cand`` are lists of normalised messages (see normalise.py) and
``options`` is the dict given in the scenario. Register with::

    from difftest.comparators import register

    @register("my_service")
    def my_service(ref, cand, options): ...

Scenario ``comparators`` entries pick them::

    {"name": "types_only", "service": "RouteAggregator",
     "match": ["afrl.cmasi.Route*"], "exclude": [], "options": {...}}

Messages are claimed by the first entry whose ``match`` globs fit the message
descriptor (and ``exclude`` does not); unclaimed messages go to the default
comparator (``canonical``). Plug-in modules are imported with ``--plugin`` or
scenario ``plugins``.
"""
import fnmatch
import importlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

DEFAULT_COMPARATOR = "canonical"
_REGISTRY: Dict[str, Callable] = {}


@dataclass
class Difference:
    kind: str                    # missing | unexpected | mismatch | count
    step: int
    type: str
    detail: str
    ref: Optional[dict] = None
    cand: Optional[dict] = None
    comparator: str = ""

    def as_dict(self):
        return self.__dict__.copy()


class UnknownComparator(KeyError):
    pass


def register(name: str):
    def deco(fn):
        _REGISTRY[name] = fn
        return fn
    return deco


def get(name: str) -> Callable:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownComparator(
            "unknown comparator %r (known: %s)" % (name, ", ".join(sorted(_REGISTRY))))


def names() -> List[str]:
    return sorted(_REGISTRY)


def load_plugin(module: str):
    importlib.import_module(module)


def field_diffs(a, b, path="") -> List[str]:
    """Human readable list of differing paths between two json values."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            p = "%s.%s" % (path, k) if path else k
            if k not in a:
                out.append("%s: only in candidate (%r)" % (p, b[k]))
            elif k not in b:
                out.append("%s: only in reference (%r)" % (p, a[k]))
            else:
                out.extend(field_diffs(a[k], b[k], p))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return ["%s: length %d != %d" % (path or "<root>", len(a), len(b))]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(field_diffs(x, y, "%s[%d]" % (path, i)))
        return out
    return [] if a == b else ["%s: %r != %r" % (path or "<root>", a, b)]


def _by_step(ref, cand):
    """Yield ``(step, ref_msgs, cand_msgs)`` for each step, in sorted order."""
    r, c = defaultdict(list), defaultdict(list)
    for m in ref:
        r[m["step"]].append(m)
    for m in cand:
        c[m["step"]].append(m)
    for step in sorted(set(r) | set(c)):
        yield step, r.get(step, []), c.get(step, [])


@register("canonical")
def canonical(ref, cand, options):
    """Strict per-window multiset equality of canonical messages."""
    diffs: List[Difference] = []
    for step, r, c in _by_step(ref, cand):
        rest_c = list(c)
        unmatched_r = []
        for m in r:
            for i, x in enumerate(rest_c):
                if x["key"] == m["key"]:
                    del rest_c[i]
                    break
            else:
                unmatched_r.append(m)
        # pair leftovers of same type as field-level mismatches
        for m in unmatched_r:
            for i, x in enumerate(rest_c):
                if x["type"] == m["type"]:
                    del rest_c[i]
                    d = field_diffs(m["msg"], x["msg"])
                    diffs.append(Difference(
                        "mismatch", step, m["type"], "; ".join(d),
                        m["msg"], x["msg"]))
                    break
            else:
                diffs.append(Difference("missing", step, m["type"],
                                        "present in reference only", m["msg"]))
        for x in rest_c:
            diffs.append(Difference("unexpected", step, x["type"],
                                    "present in candidate only", None, x["msg"]))
    return diffs


@register("types")
def types_only(ref, cand, options):
    """Compare only the multiset of message types per window (no content)."""
    diffs = []
    for step, r, c in _by_step(ref, cand):
        cr, cc = defaultdict(int), defaultdict(int)
        for m in r:
            cr[m["type"]] += 1
        for m in c:
            cc[m["type"]] += 1
        for t in sorted(set(cr) | set(cc)):
            if cr[t] != cc[t]:
                diffs.append(Difference(
                    "count", step, t, "reference=%d candidate=%d" % (cr[t], cc[t])))
    return diffs


@register("subset")
def subset(ref, cand, options):
    """Every reference message must appear in the candidate (extras allowed)."""
    diffs = []
    for d in canonical(ref, cand, options):
        if d.kind != "unexpected":
            diffs.append(d)
    return diffs


@register("ignore")
def ignore(ref, cand, options):
    """Never reports differences (explicitly waive a message family)."""
    return []


@dataclass
class ComparisonResult:
    comparator: str
    service: str
    ref_count: int
    cand_count: int
    differences: List[Difference] = field(default_factory=list)


def _claims(spec, mtype) -> bool:
    match = spec.get("match", ["*"])
    return (any(fnmatch.fnmatchcase(mtype, g) for g in match)
            and not any(fnmatch.fnmatchcase(mtype, g)
                        for g in spec.get("exclude", [])))


def compare_all(ref: List[dict], cand: List[dict],
                specs: Optional[List[dict]] = None) -> List[ComparisonResult]:
    """Dispatch normalised messages to comparators and run them."""
    specs = list(specs or [])
    # catch-all default for everything not claimed
    specs.append({"name": DEFAULT_COMPARATOR, "match": ["*"],
                  "service": "<default>", "_implicit": True})
    buckets = [([], []) for _ in specs]

    def route(messages, idx):
        for m in messages:
            for i, s in enumerate(specs):
                if _claims(s, m["type"]):
                    buckets[i][idx].append(m)
                    break

    route(ref, 0)
    route(cand, 1)
    results = []
    for spec, (r, c) in zip(specs, buckets):
        if spec.get("_implicit") and not r and not c:
            continue
        fn = get(spec["name"])
        diffs = fn(r, c, spec.get("options", {}))
        for d in diffs:
            d.comparator = spec["name"]
        results.append(ComparisonResult(
            spec["name"], spec.get("service", spec["name"]),
            len(r), len(c), diffs))
    return results
