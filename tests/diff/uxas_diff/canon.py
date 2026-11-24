"""Canonicalisation of decoded LMCP messages.

A capture is a list of *records* (plain dicts, JSON-serialisable):

    {"t_ms": int, "phase": int, "address": str, "descriptor": str,
     "content_type": str, "source_group": str,
     "source_entity_id": int, "source_service_id": int,
     "obj": {<field>: <value>, ...}}

``canonicalise`` turns records into a flat, order-independent list of
canonical messages ``{"window": int, "type": str, "obj": {...}}`` by:

* dropping transport/volatile metadata (source ids, timing, group);
* stripping volatile fields (``strip_fields``, e.g. ``Time``);
* renumbering run-specific ids (``renumber_fields``) to ordinals so
  cross references stay consistent but concrete values do not matter;
* dropping unset values (None / empty list) and rounding floats;
* assigning each message to a window and sorting by (window, type, body).
"""
import copy
import json
import math
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG: Dict[str, Any] = {
    # Fields removed everywhere (any nesting level).
    "strip_fields": ["Time", "TimeStamp", "TimeReceived", "TimeSent",
                     "CreationTime", "LogTime"],
    # Fields whose values are replaced by first-appearance ordinals.
    "renumber_fields": ["RequestID", "ResponseID", "CommandID", "PlanID",
                        "CorrelationID", "MessageID"],
    # Message types (fnmatch globs on descriptor) dropped before diffing.
    "ignore_types": [],
    # If non-empty, only these message types (globs) are kept.
    "only_types": [],
    # "phase": one window per replay step; "all": a single window;
    # integer N: fixed N ms time buckets.
    "window": "phase",
    # Significant digits kept when comparing floats.
    "float_digits": 6,
    # Drop None / [] / "" values so unset-vs-default does not matter.
    "drop_empty": True,
}


def make_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for k, v in (overrides or {}).items():
        if k not in cfg:
            raise ValueError("unknown canon option: %s" % k)
        cfg[k] = v
    return cfg


def _matches(name: str, patterns: List[str]) -> bool:
    import fnmatch
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def _norm_float(x: float, digits: int) -> Any:
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    if x == 0:
        return 0.0
    return float("%.*g" % (digits, x))


class _Ids:
    """Ordinal allocator for renumbered ids."""

    def __init__(self):
        self.table: Dict[Any, str] = {}

    def token(self, value: Any) -> str:
        key = json.dumps(value, sort_keys=True)
        if key not in self.table:
            self.table[key] = "<id:%d>" % (len(self.table) + 1)
        return self.table[key]


def _clean(value: Any, cfg: Dict[str, Any], ids: Optional[_Ids]) -> Any:
    """Recursively clean a decoded value.

    When ``ids`` is None, renumbered fields are masked with ``<id>``
    (used to compute a stable sort key before ordinals are assigned).
    """
    if isinstance(value, dict):
        out = {}
        for k in sorted(value):
            if k in cfg["strip_fields"]:
                continue
            v = _clean(value[k], cfg, ids)
            if k in cfg["renumber_fields"] and v not in (None, [], ""):
                v = _renumber(v, ids)
            if cfg["drop_empty"] and v in (None, [], ""):
                continue
            out[k] = v
        return out
    if isinstance(value, (list, tuple)):
        return [_clean(v, cfg, ids) for v in value]
    if isinstance(value, float):
        return _norm_float(value, cfg["float_digits"])
    return value


def _renumber(v: Any, ids: Optional[_Ids]) -> Any:
    if isinstance(v, list):
        return [_renumber(x, ids) for x in v]
    return "<id>" if ids is None else ids.token(v)


def _window_of(rec: Dict[str, Any], window: Any) -> int:
    if window == "all":
        return 0
    if window == "phase":
        return int(rec.get("phase", 0))
    return int(rec.get("t_ms", 0)) // int(window)


def _sort_key(m: Dict[str, Any]):
    return (m["window"], m["type"], json.dumps(m["obj"], sort_keys=True))


def canonicalise(records: List[Dict[str, Any]],
                 config: Optional[Dict[str, Any]] = None
                 ) -> List[Dict[str, Any]]:
    """Return the canonical, order-independent form of ``records``."""
    cfg = make_config(config)  # accepts overrides or a full config
    masked = []
    for rec in records:
        typ = rec.get("descriptor") or rec.get("address") or "?"
        if cfg["only_types"] and not _matches(typ, cfg["only_types"]):
            continue
        if _matches(typ, cfg["ignore_types"]):
            continue
        masked.append({"window": _window_of(rec, cfg["window"]),
                       "type": typ,
                       "raw": rec.get("obj", {})})
    # Pass 1: masked bodies give a stable order independent of id values.
    for m in masked:
        m["obj"] = _clean(m["raw"], cfg, None)
    masked.sort(key=_sort_key)
    # Pass 2: assign ordinals in that order.
    ids = _Ids()
    result = []
    for m in masked:
        result.append({"window": m["window"], "type": m["type"],
                       "obj": _clean(m["raw"], cfg, ids)})
    result.sort(key=_sort_key)
    return result
