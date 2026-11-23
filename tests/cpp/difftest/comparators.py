"""Per-descriptor comparator plug-ins (design option 2 layered on option 1).

A comparator receives the canonical messages of ONE descriptor from each
side and returns a list of human-readable difference strings (empty = match)::

    from difftest.comparators import register

    @register("my_service_cmp")
    def my_cmp(ada, cpp, params):
        ...
        return []

Scenario ``comparators`` map descriptor globs (fnmatch, most specific =
longest pattern wins) to a comparator name or ``{"name": ..., **params}``.
Descriptors with no matching entry use ``exact``.  Extra modules can be
loaded with ``plugins`` in the scenario or ``--plugin`` on the CLI; they
call :func:`register` at import time.
"""
import importlib
import json
from fnmatch import fnmatch
from typing import Any, Callable, Dict, List, Optional

Comparator = Callable[[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]], List[str]]

_REGISTRY: Dict[str, Comparator] = {}


class ComparatorError(Exception):
    pass


def register(name: str) -> Callable[[Comparator], Comparator]:
    def deco(fn: Comparator) -> Comparator:
        _REGISTRY[name] = fn
        return fn
    return deco


def get(name: str) -> Comparator:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ComparatorError("unknown comparator %r (known: %s)" %
                              (name, sorted(_REGISTRY)))


def available() -> List[str]:
    return sorted(_REGISTRY)


def load_plugin(module: str) -> None:
    try:
        importlib.import_module(module)
    except ImportError as e:
        raise ComparatorError("cannot import plugin %s: %s" % (module, e))


def _dump(m: Dict[str, Any]) -> str:
    return json.dumps(m.get("obj"), sort_keys=True)


def _multiset_diff(a, b):
    """Return (only_in_a, only_in_b) as lists of canonical dumps."""
    counts: Dict[str, int] = {}
    for m in a:
        counts[_dump(m)] = counts.get(_dump(m), 0) + 1
    only_b = []
    for m in b:
        k = _dump(m)
        if counts.get(k, 0) > 0:
            counts[k] -= 1
        else:
            only_b.append(k)
    only_a = [k for k, n in counts.items() for _ in range(n)]
    return only_a, only_b


@register("exact")
def exact(ada, cpp, params):
    only_a, only_b = _multiset_diff(ada, cpp)
    diffs = ["only in ada: %s" % k for k in sorted(only_a)]
    diffs += ["only in cpp: %s" % k for k in sorted(only_b)]
    return diffs


@register("ignore")
def ignore(ada, cpp, params):
    return []


@register("count")
def count_only(ada, cpp, params):
    if len(ada) != len(cpp):
        return ["count differs: ada=%d cpp=%d" % (len(ada), len(cpp))]
    return []


@register("cpp_superset")
def cpp_superset(ada, cpp, params):
    """Every Ada message must be present in C++ (C++ may emit extras)."""
    only_a, _ = _multiset_diff(ada, cpp)
    return ["missing in cpp: %s" % k for k in sorted(only_a)]


def _numeric_equal(a, b, abs_tol, rel_tol):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(
            _numeric_equal(a[k], b[k], abs_tol, rel_tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(
            _numeric_equal(x, y, abs_tol, rel_tol) for x, y in zip(a, b))
    return a == b


@register("numeric")
def numeric(ada, cpp, params):
    """Like exact but numbers match within ``abs`` / ``rel`` tolerance.

    Messages are paired in canonical (sorted) order.
    """
    abs_tol = float(params.get("abs", 1e-6))
    rel_tol = float(params.get("rel", 0.0))
    if len(ada) != len(cpp):
        return ["count differs: ada=%d cpp=%d" % (len(ada), len(cpp))]
    diffs = []
    for i, (a, b) in enumerate(zip(ada, cpp)):
        if not _numeric_equal(a.get("obj"), b.get("obj"), abs_tol, rel_tol):
            diffs.append("message %d differs: ada=%s cpp=%s" %
                         (i, _dump(a), _dump(b)))
    return diffs


def resolve(descriptor: str, spec: Optional[Dict[str, Any]]):
    """Pick (comparator_fn, params) for a descriptor from a scenario spec."""
    spec = spec or {}
    matches = [p for p in spec if fnmatch(descriptor, p)]
    if not matches:
        return get("exact"), {}
    # exact string match beats globs; otherwise the longest pattern wins
    best = descriptor if descriptor in matches else max(matches, key=len)
    entry = spec[best]
    if isinstance(entry, str):
        return get(entry), {}
    if isinstance(entry, dict) and "name" in entry:
        params = {k: v for k, v in entry.items() if k != "name"}
        return get(entry["name"]), params
    raise ComparatorError("bad comparator entry for %r: %r" % (best, entry))
