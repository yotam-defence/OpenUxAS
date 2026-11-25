"""Comparator plug-in registry.

A comparator is a callable ``fn(expected, actual, **options) -> [Difference]``
receiving two *canonical* messages (see normalise.py) and returning the list of
differences (empty = equivalent).  Comparators are registered by name and may
be bound to a message type and/or a service name::

    from difftest.comparators import comparator

    @comparator("my_cmp", message_type="AirVehicleState", service="Sim")
    def my_cmp(expected, actual, **options):
        return []

Resolution order for a message: (type, service) binding, type binding, service
binding, default comparator.  ``type`` matches the full or the short LMCP
name.  Scenarios can bind additional comparators (with options) through their
``comparators`` list and external plug-ins are loaded with ``--plugin``.
"""
import functools
import importlib
import importlib.util
import json
import math
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from difftest.normalise import short_type


class Difference:
    """One difference between expected and actual output."""

    def __init__(self, window: str, kind: str, path: str = "",
                 expected: Any = None, actual: Any = None,
                 msg_type: str = "", detail: str = ""):
        self.window = window
        self.kind = kind          # value|missing_field|extra_field|length|
        #                           missing_message|extra_message|count
        self.path = path
        self.expected = expected
        self.actual = actual
        self.msg_type = msg_type
        self.detail = detail

    def __repr__(self):
        return "Difference(%s)" % self

    def __str__(self):
        loc = "[%s] %s" % (self.window, self.msg_type) if self.msg_type \
            else "[%s]" % self.window
        if self.path:
            loc += " " + self.path
        if self.kind in ("missing_message", "extra_message"):
            body = "%s: %s" % (self.kind, _short(
                self.expected if self.kind == "missing_message"
                else self.actual))
        elif self.kind == "count":
            body = self.detail
        else:
            body = "%s: expected %s, actual %s" % (
                self.kind, _short(self.expected), _short(self.actual))
        return "%s: %s" % (loc, body)

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in ("", None)}


def _short(v: Any, limit: int = 160) -> str:
    s = json.dumps(v, sort_keys=True, default=str)
    return s if len(s) <= limit else s[:limit - 3] + "..."


def diff_values(expected: Any, actual: Any, path: str = "",
                leaf: Optional[Callable[[Any, Any], bool]] = None
                ) -> List[Tuple[str, str, Any, Any]]:
    """Structural diff -> list of (kind, path, expected, actual)."""
    leaf = leaf or (lambda a, b: a == b)
    out: List[Tuple[str, str, Any, Any]] = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for k in sorted(set(expected) | set(actual)):
            p = "%s.%s" % (path, k) if path else k
            if k not in actual:
                out.append(("missing_field", p, expected[k], None))
            elif k not in expected:
                out.append(("extra_field", p, None, actual[k]))
            else:
                out.extend(diff_values(expected[k], actual[k], p, leaf))
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            out.append(("length", path, len(expected), len(actual)))
        for i, (a, b) in enumerate(zip(expected, actual)):
            out.extend(diff_values(a, b, "%s[%d]" % (path, i), leaf))
    elif not leaf(expected, actual):
        out.append(("value", path, expected, actual))
    return out


Comparator = Callable[..., List[Difference]]


def _to_differences(raw, msg_type: str = "") -> List[Difference]:
    return [Difference("", k, p, e, a, msg_type) for k, p, e, a in raw]


# --------------------------------------------------------------------------
# Built-in comparators
# --------------------------------------------------------------------------

def default_comparator(expected, actual, **options) -> List[Difference]:
    """Exact comparison of canonical messages (header and fields)."""
    return _to_differences(diff_values(expected, actual), expected["type"])


def float_tolerance_comparator(expected, actual, rel: float = 1e-5,
                               abs: float = 1e-6, **options):
    """Like default, but floats match within ``rel``/``abs`` tolerance."""
    def leaf(a, b):
        if isinstance(a, float) and isinstance(b, float):
            return math.isclose(a, b, rel_tol=rel, abs_tol=abs)
        return a == b
    return _to_differences(diff_values(expected, actual, leaf=leaf),
                           expected["type"])


def ignore_fields_comparator(expected, actual, fields=(), **options):
    """Default comparison ignoring the listed field names (any depth)."""
    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if k not in fields}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v
    return default_comparator(strip(expected), strip(actual))


def ignore_comparator(expected, actual, **options) -> List[Difference]:
    """Messages of this type/service are considered equivalent."""
    return []


class ComparatorRegistry:
    """Named comparators plus (type, service) bindings."""

    def __init__(self):
        self.named: Dict[str, Comparator] = {}
        self.bindings: List[Tuple[Optional[str], Optional[str], Comparator]] \
            = []
        self.default: Comparator = default_comparator

    def register(self, name: str, fn: Comparator,
                 message_type: Optional[str] = None,
                 service: Optional[str] = None) -> Comparator:
        self.named[name] = fn
        if message_type or service:
            self.bind(message_type, service, fn)
        return fn

    def bind(self, message_type: Optional[str], service: Optional[str],
             fn: Comparator) -> None:
        """Bind a comparator; later bindings override earlier ones."""
        self.bindings = [b for b in self.bindings
                         if (b[0], b[1]) != (message_type, service)]
        self.bindings.append((message_type, service, fn))

    def bind_named(self, name: str, message_type=None, service=None,
                   options: Optional[Dict[str, Any]] = None) -> None:
        if name not in self.named:
            raise KeyError("unknown comparator %r (known: %s)" %
                           (name, sorted(self.named)))
        fn = self.named[name]
        if options:
            fn = functools.partial(fn, **options)
        self.bind(message_type, service, fn)

    def resolve(self, msg: Dict[str, Any]) -> Comparator:
        t, s = msg["type"], msg.get("service")
        best, best_rank = self.default, -1
        for bt, bs, fn in self.bindings:
            if bt is not None and bt not in (t, short_type(t)):
                continue
            if bs is not None and bs != s:
                continue
            # both > type only > service only > default
            rank = (2 if bt else 0) + (1 if bs else 0)
            if rank >= best_rank:
                best, best_rank = fn, rank
        return best

    def clone(self) -> "ComparatorRegistry":
        r = ComparatorRegistry()
        r.named = dict(self.named)
        r.bindings = list(self.bindings)
        r.default = self.default
        return r


DEFAULT_REGISTRY = ComparatorRegistry()
for _n, _f in (("default", default_comparator),
               ("float_tolerance", float_tolerance_comparator),
               ("ignore_fields", ignore_fields_comparator),
               ("ignore", ignore_comparator)):
    DEFAULT_REGISTRY.register(_n, _f)


def comparator(name: str, message_type: Optional[str] = None,
               service: Optional[str] = None,
               registry: Optional[ComparatorRegistry] = None):
    """Decorator registering a comparator in the (default) registry."""
    def deco(fn: Comparator) -> Comparator:
        (registry or DEFAULT_REGISTRY).register(name, fn, message_type,
                                                service)
        return fn
    return deco


def load_plugin(spec: str) -> None:
    """Import a plug-in given as a ``.py`` path or a dotted module name.

    Importing is enough: modules register through the ``@comparator``
    decorator.  A module-level ``register(registry)`` function, if present,
    is also called with the default registry.
    """
    if spec.endswith(".py") or os.sep in spec:
        name = "difftest_plugin_" + os.path.splitext(
            os.path.basename(spec))[0]
        s = importlib.util.spec_from_file_location(name, spec)
        if s is None or s.loader is None:
            raise ImportError("cannot load plugin %s" % spec)
        mod = importlib.util.module_from_spec(s)
        s.loader.exec_module(mod)
    else:
        mod = importlib.import_module(spec)
    if hasattr(mod, "register"):
        mod.register(DEFAULT_REGISTRY)


# --------------------------------------------------------------------------
# Window comparison
# --------------------------------------------------------------------------

def compare_messages(expected: List[Dict[str, Any]],
                     actual: List[Dict[str, Any]],
                     registry: ComparatorRegistry,
                     window: str,
                     ordered: bool = False) -> List[Difference]:
    """Compare two lists of canonical messages of one window."""
    diffs: List[Difference] = []

    def run(e, a) -> List[Difference]:
        ds = registry.resolve(e)(e, a)
        for d in ds:
            d.window = window
            d.msg_type = d.msg_type or e["type"]
        return ds

    if ordered:
        for e, a in zip(expected, actual):
            if e["type"] != a["type"]:
                diffs.append(Difference(window, "value", "type", e["type"],
                                        a["type"], e["type"]))
            else:
                diffs.extend(run(e, a))
        for e in expected[len(actual):]:
            diffs.append(Difference(window, "missing_message", expected=e,
                                    msg_type=e["type"]))
        for a in actual[len(expected):]:
            diffs.append(Difference(window, "extra_message", actual=a,
                                    msg_type=a["type"]))
        return diffs

    types = sorted({m["type"] for m in expected} | {m["type"] for m in actual})
    for t in types:
        exp = [m for m in expected if m["type"] == t]
        act = [m for m in actual if m["type"] == t]
        if len(exp) != len(act):
            diffs.append(Difference(
                window, "count", msg_type=t, expected=len(exp),
                actual=len(act),
                detail="%d message(s) expected, %d actual" %
                       (len(exp), len(act))))
        # Pass 1: pair messages that the comparator deems equivalent
        left_e, left_a = [], list(act)
        for e in exp:
            for i, a in enumerate(left_a):
                if not run(e, a):
                    del left_a[i]
                    break
            else:
                left_e.append(e)
        # Pass 2: pair the rest in canonical order and report field diffs
        for e, a in zip(left_e, left_a):
            diffs.extend(run(e, a))
        for e in left_e[len(left_a):]:
            diffs.append(Difference(window, "missing_message", expected=e,
                                    msg_type=t))
        for a in left_a[len(left_e):]:
            diffs.append(Difference(window, "extra_message", actual=a,
                                    msg_type=t))
    return diffs


def compare_captures(expected: Dict[str, List[Dict[str, Any]]],
                     actual: Dict[str, List[Dict[str, Any]]],
                     registry: Optional[ComparatorRegistry] = None,
                     ordered_windows: Tuple[str, ...] = ()
                     ) -> List[Difference]:
    """Compare normalised captures window by window."""
    registry = registry or DEFAULT_REGISTRY
    diffs: List[Difference] = []
    for name in expected:
        if name not in actual:
            diffs.append(Difference(name, "count",
                                    detail="window missing in actual"))
            continue
        diffs.extend(compare_messages(expected[name], actual[name], registry,
                                      name, name in ordered_windows))
    for name in actual:
        if name not in expected:
            diffs.append(Difference(name, "count",
                                    detail="window missing in expected"))
    return diffs
