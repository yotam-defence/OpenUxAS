"""Per-service comparator plug-in registry.

A comparator is ``fn(ref, test, ctx) -> list[str]`` receiving two lists of
canonical messages (all of one message type, see canon.py) and returning a
list of human readable mismatch lines (empty == equal). ``ctx`` is a dict
with ``type`` (the descriptor) and ``scenario`` (the scenario dict, or {}).

Register with the decorator::

    from uxas_diff.comparators import comparator

    @comparator("route_plan_cost")
    def route_plan_cost(ref, test, ctx):
        ...

and select it from a scenario with
``"comparators": {"uxas.messages.route.RoutePlanResponse": "route_plan_cost"}``.
Plug-in modules are loaded by scenario ``"plugins"`` entries or ``--plugin``.
"""
import importlib
import importlib.util
import json
import os
from typing import Callable, Dict, List

Comparator = Callable[[list, list, dict], List[str]]

_REGISTRY: Dict[str, Comparator] = {}


class UnknownComparator(KeyError):
    pass


def register(name: str, fn: Comparator, replace: bool = False) -> Comparator:
    if name in _REGISTRY and not replace:
        raise ValueError("comparator already registered: %s" % name)
    _REGISTRY[name] = fn
    return fn


def comparator(name: str, replace: bool = False):
    def deco(fn: Comparator) -> Comparator:
        return register(name, fn, replace)
    return deco


def get(name: str) -> Comparator:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownComparator(
            "unknown comparator %r (registered: %s)"
            % (name, ", ".join(sorted(_REGISTRY))))


def names() -> List[str]:
    return sorted(_REGISTRY)


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)


def load_plugin(spec: str) -> None:
    """Import a plug-in by module name or by .py file path."""
    if spec.endswith(".py") or os.sep in spec:
        mod_name = "uxas_diff_plugin_" + \
            os.path.splitext(os.path.basename(spec))[0]
        s = importlib.util.spec_from_file_location(mod_name, spec)
        if s is None or s.loader is None:
            raise ImportError("cannot load plugin %s" % spec)
        mod = importlib.util.module_from_spec(s)
        s.loader.exec_module(mod)
    else:
        importlib.import_module(spec)


def _key(m: dict) -> str:
    return json.dumps(m, sort_keys=True)


def _fmt(m: dict) -> str:
    return "[w%s] %s" % (m.get("window"), json.dumps(m.get("obj"),
                                                      sort_keys=True))


@comparator("canonical")
def canonical(ref, test, ctx):
    """Multiset equality of canonical messages (the default)."""
    out: List[str] = []
    remaining = list(test)
    keys = [_key(m) for m in remaining]
    for m in ref:
        k = _key(m)
        if k in keys:
            i = keys.index(k)
            keys.pop(i)
            remaining.pop(i)
        else:
            out.append("missing in test: " + _fmt(m))
    for m in remaining:
        out.append("unexpected in test: " + _fmt(m))
    return out


@comparator("count")
def count(ref, test, ctx):
    """Only compare how many messages of the type appear per window."""
    def per_window(ms):
        d: Dict[int, int] = {}
        for m in ms:
            d[m["window"]] = d.get(m["window"], 0) + 1
        return d
    a, b = per_window(ref), per_window(test)
    return ["window %s: ref has %d, test has %d" % (w, a.get(w, 0), b.get(w, 0))
            for w in sorted(set(a) | set(b)) if a.get(w, 0) != b.get(w, 0)]


@comparator("ignore")
def ignore(ref, test, ctx):
    """Never reports a mismatch."""
    return []
