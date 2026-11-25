"""Comparator plug-in registry.

Writing a comparator (for milestones adding service-specific equivalence)::

    from diffharness.comparators import Comparator, register_comparator

    @register_comparator("waypoint_plan")
    class WaypointPlanComparator(Comparator):
        # Optional: options accepted from the scenario's
        # "comparator": {"name": "waypoint_plan", "options": {...}}
        def __init__(self, **options):
            super().__init__(**options)

        def normalise(self, records):
            # records: list of plain records (see codec.py); must return a
            # list of JSON-serialisable normalised messages.  Reuse
            # self.normaliser_options / diffharness.normalise.normalise.
            return super().normalise(records)

        def render(self, normalised):
            # list[str]; this text is what gets diffed (one logical item
            # per line makes for readable diffs).
            return super().render(normalised)

Plug-ins are discovered by importing the modules named in the environment
variable ``DIFFHARNESS_PLUGINS`` (comma separated), by ``--plugin MODULE`` on
the CLI, and by the ``diffharness.comparators_ext`` package if present.
A scenario selects a comparator by name and may override it per message type
with ``comparator.by_type``.
"""
import importlib
import json
import os
from typing import Any, Callable, Dict, Iterable, List, Optional, Type

from diffharness.normalise import NormaliseOptions, normalise
from diffharness.scenario import ComparatorSpec

_REGISTRY: Dict[str, Type["Comparator"]] = {}


class UnknownComparator(KeyError):
    pass


class Comparator:
    """Base class: canonicalise, render, decide equivalence."""

    name = "base"

    def __init__(self, **options: Any):
        self.options = options
        self.normaliser_options = NormaliseOptions.from_options(
            options.get("normalise"))

    def normalise(self, records: List[Dict[str, Any]]) -> List[Any]:
        return normalise(records, self.normaliser_options)

    def render(self, normalised: List[Any]) -> List[str]:
        lines: List[str] = []
        for m in normalised:
            lines.append("== window %d: %s" % (m["window"], m["type"]))
            env = m.get("envelope") or {}
            if env:
                lines.append("   envelope: " + json.dumps(env,
                                                          sort_keys=True))
            lines.extend("   " + l for l in json.dumps(
                m["obj"], sort_keys=True, indent=2).splitlines())
        return lines

    def equivalent(self, expected: List[str], actual: List[str]) -> bool:
        """Decide equivalence of two rendered texts (default: equality)."""
        return expected == actual


def register_comparator(name: str) -> Callable[[Type[Comparator]],
                                               Type[Comparator]]:
    def deco(cls: Type[Comparator]) -> Type[Comparator]:
        if name in _REGISTRY and _REGISTRY[name] is not cls:
            raise ValueError("comparator %r already registered" % name)
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return deco


@register_comparator("canonical")
class CanonicalComparator(Comparator):
    """Default: strip volatile fields, window-sort, compare."""


@register_comparator("strict")
class StrictComparator(Comparator):
    """No stripping, no sorting: for debugging the harness itself."""

    def __init__(self, **options: Any):
        norm = {"strip_fields": [], "remap_fields": [], "strip_envelope": [],
                "sort": False}
        norm.update(options.get("normalise") or {})
        super().__init__(**dict(options, normalise=norm))


def load_plugins(modules: Iterable[str] = ()) -> None:
    names = [m for m in os.environ.get("DIFFHARNESS_PLUGINS", "").split(",")
             if m.strip()]
    names += list(modules)
    for n in names:
        importlib.import_module(n.strip())
    try:
        importlib.import_module("diffharness.comparators_ext")
    except ModuleNotFoundError as e:
        if e.name != "diffharness.comparators_ext":
            raise


def available_comparators() -> List[str]:
    return sorted(_REGISTRY)


def get_comparator(spec: Optional[ComparatorSpec] = None,
                   name: Optional[str] = None,
                   options: Optional[Dict[str, Any]] = None) -> Comparator:
    if spec is not None:
        name, options = spec.name, spec.options
    name = name or "canonical"
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise UnknownComparator(
            "unknown comparator %r (available: %s)"
            % (name, ", ".join(available_comparators())))
    return cls(**(options or {}))


def _type_of(rec: Dict[str, Any]) -> str:
    return rec.get("obj", {}).get("$type", rec.get("descriptor", ""))


def compare_records(expected: List[Dict[str, Any]],
                    actual: List[Dict[str, Any]],
                    spec: ComparatorSpec):
    """Run the scenario's comparator(s) over two record lists.

    Returns ``(equal, expected_lines, actual_lines)``.  Message types listed
    in ``spec.by_type`` are routed to their own comparator and rendered in a
    separate section.
    """
    sections = [("", get_comparator(spec),
                 lambda t: t not in spec.by_type)]
    for t, sub in sorted(spec.by_type.items()):
        sections.append(("[%s via %s] " % (t, sub.name), get_comparator(sub),
                         lambda x, t=t: x == t))
    exp_lines: List[str] = []
    act_lines: List[str] = []
    equal = True
    for label, comp, pick in sections:
        e = [r for r in expected if pick(_type_of(r))]
        a = [r for r in actual if pick(_type_of(r))]
        el = comp.render(comp.normalise(e))
        al = comp.render(comp.normalise(a))
        if label:
            el = ["#### " + label] + el
            al = ["#### " + label] + al
        equal = equal and comp.equivalent(el, al)
        exp_lines += el
        act_lines += al
    return equal, exp_lines, act_lines
