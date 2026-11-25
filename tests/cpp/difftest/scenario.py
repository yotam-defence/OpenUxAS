"""Scenario loading and validation.

A scenario is a JSON document, see README.md for the full format::

    {
      "name": "smoke",
      "steps": [
        {"send": {"type": "KeyValuePair", "fields": {"Key": "k", "Value": "v"}}},
        {"delay_ms": 100},
        {"expect_window": {"name": "w1", "duration_ms": 500}}
      ]
    }
"""
import copy
import json
import os
from typing import Any, Dict, List

from difftest.model import (ConfigSpec, DelayStep, Scenario, SendStep,
                            ServiceSpec, WindowStep)


class ScenarioError(Exception):
    """Raised when a scenario file is malformed."""


_TOP_KEYS = {"name", "description", "startup_settle_ms", "shutdown_settle_ms",
             "capture_startup", "config", "normalise", "comparators",
             "services", "steps"}
_STEP_KEYS = {"delay_ms", "send", "expect_window"}
_SEND_KEYS = {"type", "fields", "source_entity_id", "source_service_id",
              "source_group", "repeat", "interval_ms"}
_WINDOW_KEYS = {"name", "duration_ms", "ordered", "types", "min_messages",
                "max_messages"}
_CONFIG_KEYS = {"entity_id", "entity_type", "services", "bridge_subscriptions"}
_SERVICE_KEYS = {"type", "attributes", "children", "impls"}


def _check_keys(where: str, obj: Dict[str, Any], allowed) -> None:
    if not isinstance(obj, dict):
        raise ScenarioError("%s: expected an object, got %s" %
                            (where, type(obj).__name__))
    unknown = set(obj) - set(allowed)
    if unknown:
        raise ScenarioError("%s: unknown key(s) %s (allowed: %s)" %
                            (where, sorted(unknown), sorted(allowed)))


def _nonneg_int(where: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ScenarioError("%s: expected a non-negative integer, got %r" %
                            (where, value))
    return value


def _subst(value: Any, i: int) -> Any:
    """Replace ``${i}`` in every string of a JSON value (for ``repeat``)."""
    if isinstance(value, str):
        return value.replace("${i}", str(i))
    if isinstance(value, list):
        return [_subst(v, i) for v in value]
    if isinstance(value, dict):
        return {k: _subst(v, i) for k, v in value.items()}
    return value


def _parse_service(where: str, raw: Dict[str, Any]) -> ServiceSpec:
    _check_keys(where, raw, _SERVICE_KEYS)
    t = raw.get("type")
    if isinstance(t, str):
        ada = cpp = t
    elif isinstance(t, dict) and set(t) == {"ada", "cpp"} and \
            all(isinstance(v, str) for v in t.values()):
        ada, cpp = t["ada"], t["cpp"]
    else:
        raise ScenarioError(
            '%s: "type" must be a string or {"ada": str, "cpp": str}' % where)
    impls = raw.get("impls")
    if impls is not None and (not isinstance(impls, list) or
                              not set(impls) <= {"ada", "cpp"}):
        raise ScenarioError('%s: "impls" must be a subset of ["ada","cpp"]'
                            % where)
    attrs = raw.get("attributes", {})
    if not isinstance(attrs, dict):
        raise ScenarioError('%s: "attributes" must be an object' % where)
    return ServiceSpec(type_ada=ada, type_cpp=cpp,
                       attributes={k: str(v) for k, v in attrs.items()},
                       children=list(raw.get("children", [])),
                       impls=impls)


def _parse_config(raw: Dict[str, Any]) -> ConfigSpec:
    _check_keys("config", raw, _CONFIG_KEYS)
    cfg = ConfigSpec()
    if "entity_id" in raw:
        cfg.entity_id = _nonneg_int("config.entity_id", raw["entity_id"])
    cfg.entity_type = raw.get("entity_type", cfg.entity_type)
    cfg.bridge_subscriptions = raw.get("bridge_subscriptions")
    for n, s in enumerate(raw.get("services", [])):
        cfg.services.append(_parse_service("config.services[%d]" % n, s))
    return cfg


def _parse_steps(raw_steps: Any) -> List[Any]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ScenarioError('"steps" must be a non-empty list')
    steps: List[Any] = []
    names = set()
    for n, raw in enumerate(raw_steps):
        where = "steps[%d]" % n
        _check_keys(where, raw, _STEP_KEYS)
        if len(raw) != 1:
            raise ScenarioError(
                "%s: exactly one of %s required" % (where, sorted(_STEP_KEYS)))
        kind, body = next(iter(raw.items()))
        if kind == "delay_ms":
            steps.append(DelayStep(_nonneg_int(where + ".delay_ms", body)))
        elif kind == "send":
            _check_keys(where + ".send", body, _SEND_KEYS)
            if not isinstance(body.get("type"), str):
                raise ScenarioError('%s.send: "type" (string) required' %
                                    where)
            repeat = _nonneg_int(where + ".send.repeat",
                                 body.get("repeat", 1))
            interval = _nonneg_int(where + ".send.interval_ms",
                                   body.get("interval_ms", 0))
            if repeat == 0:
                raise ScenarioError("%s.send.repeat must be >= 1" % where)
            for i in range(repeat):
                spec = {"type": body["type"],
                        "fields": _subst(copy.deepcopy(
                            body.get("fields", {})), i)}
                steps.append(SendStep(
                    spec=spec,
                    source_entity_id=body.get("source_entity_id"),
                    source_service_id=body.get("source_service_id", 0),
                    source_group=_subst(body.get("source_group", ""), i)))
                if interval and i != repeat - 1:
                    steps.append(DelayStep(interval))
        else:  # expect_window
            _check_keys(where + ".expect_window", body, _WINDOW_KEYS)
            name = body.get("name")
            if not isinstance(name, str) or not name:
                raise ScenarioError(
                    '%s.expect_window: "name" (string) required' % where)
            if name in names or name.startswith("__"):
                raise ScenarioError(
                    "%s.expect_window: duplicate or reserved name %r" %
                    (where, name))
            names.add(name)
            steps.append(WindowStep(
                name=name,
                duration_ms=_nonneg_int(where + ".duration_ms",
                                        body.get("duration_ms", 500)),
                ordered=bool(body.get("ordered", False)),
                types=body.get("types"),
                min_messages=body.get("min_messages"),
                max_messages=body.get("max_messages")))
    if not any(isinstance(s, WindowStep) for s in steps):
        raise ScenarioError("scenario needs at least one expect_window step")
    if not isinstance(steps[-1], WindowStep):
        raise ScenarioError("last step must be an expect_window (otherwise "
                            "trailing output would never be captured)")
    return steps


def parse_scenario(raw: Dict[str, Any], path: str = None) -> Scenario:
    """Validate a decoded JSON document and build a Scenario."""
    _check_keys("scenario", raw, _TOP_KEYS)
    name = raw.get("name")
    if not isinstance(name, str) or not name or \
            any(c in name for c in "/\\ "):
        raise ScenarioError('"name" must be a non-empty string without '
                            "spaces or path separators")
    comparators = raw.get("comparators", [])
    if not isinstance(comparators, list):
        raise ScenarioError('"comparators" must be a list')
    for n, c in enumerate(comparators):
        _check_keys("comparators[%d]" % n, c,
                    {"type", "service", "comparator", "options"})
        if "comparator" not in c:
            raise ScenarioError('comparators[%d]: "comparator" required' % n)
    services = raw.get("services", {})
    if not isinstance(services, dict):
        raise ScenarioError('"services" must map service id -> name')
    return Scenario(
        name=name,
        description=raw.get("description", ""),
        path=path,
        startup_settle_ms=_nonneg_int("startup_settle_ms",
                                      raw.get("startup_settle_ms", 1500)),
        shutdown_settle_ms=_nonneg_int("shutdown_settle_ms",
                                       raw.get("shutdown_settle_ms", 200)),
        capture_startup=bool(raw.get("capture_startup", False)),
        config=_parse_config(raw.get("config", {})),
        normalise=raw.get("normalise", {}),
        comparators=comparators,
        services={str(k): str(v) for k, v in services.items()},
        steps=_parse_steps(raw.get("steps")),
        raw=raw)


def load_scenario(path: str) -> Scenario:
    """Load a scenario JSON file."""
    try:
        with open(path, encoding="utf-8") as fd:
            raw = json.load(fd)
    except OSError as e:
        raise ScenarioError("cannot read %s: %s" % (path, e))
    except ValueError as e:
        raise ScenarioError("%s: invalid JSON: %s" % (path, e))
    try:
        return parse_scenario(raw, path)
    except ScenarioError as e:
        raise ScenarioError("%s: %s" % (path, e))


def scenario_digest(scenario: Scenario) -> str:
    """Stable hash of the scenario content (used to detect stale goldens)."""
    import hashlib
    blob = json.dumps(scenario.raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def find_scenarios(root: str) -> List[str]:
    """List ``*.json`` scenario files under ``root`` (sorted)."""
    out = []
    for d, _, files in os.walk(root):
        out.extend(os.path.join(d, f) for f in files if f.endswith(".json"))
    return sorted(out)


def build_object(spec: Dict[str, Any]):
    """Build a pylmcp ``Object`` from ``{"type": ..., "fields": {...}}``.

    Nested objects inside ``fields`` use ``{"$type": ..., <field>: ...}``.
    pylmcp (and its e3 dependency) is imported lazily so that the rest of
    the harness stays importable without it.
    """
    from pylmcp import Object  # noqa: E402

    def conv(v):
        if isinstance(v, dict):
            if "$type" not in v:
                raise ScenarioError("nested object needs a $type: %r" % v)
            kw = {k: conv(x) for k, x in v.items() if k != "$type"}
            return Object(class_name=v["$type"], **kw)
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v

    kwargs = {k: conv(v) for k, v in spec.get("fields", {}).items()}
    return Object(class_name=spec["type"], **kwargs)
