"""Per-service comparator plug-ins (design option 2 as an extension point).

The default comparator ``exact`` implements option 1: the canonical
multiset of messages of a window must be equal.  Scenarios can route message
types to other comparators with glob rules::

    "comparators": [
      {"match": "afrl.cmasi.Route*", "use": "tolerance",
       "options": {"abs": 1e-3}, "service": "RouteAggregatorService"},
      {"match": "uxas.messages.uxnative.*", "use": "ignore"}
    ]

Custom plug-ins subclass :class:`Comparator` and are referenced as
``"package.module:ClassName"`` or ``"/path/to/file.py:ClassName"`` in ``use``.
Service milestones (3-6) put theirs next to their scenarios.
"""
from __future__ import annotations

import fnmatch
import importlib
import importlib.util
import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type

from .canonical import CanonMessage


@dataclass
class Difference:
    window: int
    kind: str          # missing | unexpected | changed | count
    type: str
    detail: str = ""
    ref: Optional[str] = None
    got: Optional[str] = None


class Comparator:
    """Base class.  Subclasses override :meth:`compare`.

    ``ref`` is the reference (Ada) and ``got`` the candidate (C++) list of
    canonical messages of one window, restricted to the types routed to this
    comparator.  Return a list of :class:`Difference`.
    """

    name = "base"

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.ignore_fields = set(options.get("ignore_fields", []))

    def prepare(self, msg: CanonMessage) -> CanonMessage:
        """Optional per-message hook (default: apply ``ignore_fields``)."""
        if not self.ignore_fields:
            return msg
        import json
        body = _drop(msg.body, self.ignore_fields)
        key = msg.type + " " + json.dumps(body, sort_keys=True,
                                          separators=(",", ":"))
        return CanonMessage(msg.type, body, msg.window, key)

    def compare(self, window: int, ref: List[CanonMessage],
                got: List[CanonMessage]) -> List[Difference]:
        raise NotImplementedError


def _drop(v: Any, names: set) -> Any:
    if isinstance(v, dict):
        return {k: _drop(x, names) for k, x in v.items() if k not in names}
    if isinstance(v, list):
        return [_drop(x, names) for x in v]
    return v


COMPARATORS: Dict[str, Type[Comparator]] = {}


def register(name: str):
    def deco(cls: Type[Comparator]) -> Type[Comparator]:
        cls.name = name
        COMPARATORS[name] = cls
        return cls
    return deco


@register("exact")
class ExactComparator(Comparator):
    """Canonical multiset equality."""

    def compare(self, window, ref, got):
        rc = Counter(m.key for m in map(self.prepare, ref))
        gc = Counter(m.key for m in map(self.prepare, got))
        diffs = []
        for key in sorted((rc - gc).elements()):
            diffs.append(Difference(window, "missing", key.split(" ", 1)[0],
                                    "present in reference only", ref=key))
        for key in sorted((gc - rc).elements()):
            diffs.append(Difference(window, "unexpected",
                                    key.split(" ", 1)[0],
                                    "present in candidate only", got=key))
        return diffs


@register("ignore")
class IgnoreComparator(Comparator):
    """Never reports a difference (type is deliberately out of scope)."""

    def compare(self, window, ref, got):
        return []


@register("types_only")
class TypesOnlyComparator(Comparator):
    """Compare only how many messages of each type were produced."""

    def compare(self, window, ref, got):
        rc = Counter(m.type for m in ref)
        gc = Counter(m.type for m in got)
        return [Difference(window, "count", t,
                           "reference=%d candidate=%d" % (rc[t], gc[t]))
                for t in sorted(set(rc) | set(gc)) if rc[t] != gc[t]]


@register("distinct")
class DistinctComparator(Comparator):
    """Set equality of canonical messages, ignoring multiplicity.

    For timer driven publishers (e.g. HelloWorld) the *number* of messages
    depends on wall-clock timing, but the distinct content must match and at
    least one message must be present on both sides.
    """

    def compare(self, window, ref, got):
        rk = {m.key for m in map(self.prepare, ref)}
        gk = {m.key for m in map(self.prepare, got)}
        diffs = [Difference(window, "missing", k.split(" ", 1)[0],
                            "present in reference only", ref=k)
                 for k in sorted(rk - gk)]
        diffs += [Difference(window, "unexpected", k.split(" ", 1)[0],
                             "present in candidate only", got=k)
                  for k in sorted(gk - rk)]
        return diffs


@register("tolerance")
class ToleranceComparator(Comparator):
    """Like exact but numbers may differ by ``abs``/``rel`` tolerance.

    Messages of the same type are paired in canonical order; unpaired ones
    are reported as missing/unexpected.  Options: ``abs`` (default 1e-6),
    ``rel`` (default 0), ``ignore_fields``.
    """

    def compare(self, window, ref, got):
        tol_abs = float(self.options.get("abs", 1e-6))
        tol_rel = float(self.options.get("rel", 0.0))
        by_type_r: Dict[str, List[CanonMessage]] = defaultdict(list)
        by_type_g: Dict[str, List[CanonMessage]] = defaultdict(list)
        for m in ref:
            by_type_r[m.type].append(self.prepare(m))
        for m in got:
            by_type_g[m.type].append(self.prepare(m))
        diffs: List[Difference] = []
        for t in sorted(set(by_type_r) | set(by_type_g)):
            rs, gs = by_type_r[t], by_type_g[t]
            # exact matches cancel out; the rest is paired in canonical order
            rest_r = _remaining(rs, gs)
            rest_g = _remaining(gs, rs)
            for r, g in zip(rest_r, rest_g):
                if not _close(r.body, g.body, tol_abs, tol_rel):
                    diffs.append(Difference(
                        window, "changed", t, "values differ beyond "
                        "tolerance (abs=%g rel=%g)" % (tol_abs, tol_rel),
                        ref=r.key, got=g.key))
            for r in rest_r[len(rest_g):]:
                diffs.append(Difference(window, "missing", t,
                                        "present in reference only",
                                        ref=r.key))
            for g in rest_g[len(rest_r):]:
                diffs.append(Difference(window, "unexpected", t,
                                        "present in candidate only",
                                        got=g.key))
        return diffs


def _remaining(gs: List[CanonMessage], rs: List[CanonMessage]
               ) -> List[CanonMessage]:
    """Messages of ``gs`` not exactly matched by a message of ``rs``."""
    rkeys = Counter(r.key for r in rs)
    out = []
    for g in gs:
        if rkeys[g.key] > 0:
            rkeys[g.key] -= 1
        else:
            out.append(g)
    return out


def _close(a: Any, b: Any, tol_abs: float, tol_rel: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=tol_rel, abs_tol=tol_abs)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(
            _close(a[k], b[k], tol_abs, tol_rel) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(
            _close(x, y, tol_abs, tol_rel) for x, y in zip(a, b))
    return a == b


# ------------------------------------------------------------- plug-in API

def load_comparator_class(spec: str) -> Type[Comparator]:
    """Resolve a ``use`` value to a Comparator class."""
    if spec in COMPARATORS:
        return COMPARATORS[spec]
    if ":" not in spec:
        raise ValueError("unknown comparator %r (builtin: %s; plug-ins use "
                         "'module:Class' or 'file.py:Class')" %
                         (spec, sorted(COMPARATORS)))
    mod_spec, _, cls_name = spec.rpartition(":")
    if mod_spec.endswith(".py") or os.sep in mod_spec:
        s = importlib.util.spec_from_file_location(
            "_diff_plugin_" + os.path.basename(mod_spec)[:-3], mod_spec)
        if s is None or s.loader is None:
            raise ValueError("cannot load plug-in file %s" % mod_spec)
        mod = importlib.util.module_from_spec(s)
        s.loader.exec_module(mod)
    else:
        mod = importlib.import_module(mod_spec)
    cls = getattr(mod, cls_name, None)
    if not (isinstance(cls, type) and issubclass(cls, Comparator)):
        raise ValueError("%s is not a Comparator subclass" % spec)
    return cls


class ComparatorSet:
    """Ordered glob rules mapping message types to comparators."""

    def __init__(self, rules=(), default: Optional[Comparator] = None):
        self.rules = []     # list of (patterns, comparator)
        self.default = default or ExactComparator()
        for r in rules:
            cls = load_comparator_class(r.use)
            self.rules.append((list(r.match), cls(**r.options)))

    def select(self, type_name: str) -> Comparator:
        short = type_name.rsplit(".", 1)[-1]
        for patterns, comp in self.rules:
            if any(fnmatch.fnmatchcase(type_name, p) or
                   fnmatch.fnmatchcase(short, p) for p in patterns):
                return comp
        return self.default
