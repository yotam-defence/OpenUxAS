"""Decoded-message canonicalisation.

Messages are compared *semantically* (decoded LMCP objects), never as bytes.
Canonicalisation:

* volatile fields (timestamps, ...) are removed at any depth;
* generated identifier fields are *renumbered* in order of first occurrence
  (``CommandID: 4711`` -> ``"<CommandID#1>"``) so that relations between
  messages are preserved while the concrete values are not compared;
* header noise (source service id, optionally entity id) is dropped and the
  service id is mapped to a service name when the scenario provides one;
* floats are rounded to ``float_digits`` significant digits, NaN/inf are made
  JSON-safe, ``-0.0`` becomes ``0.0``, bytes become hex strings;
* inside a window messages are sorted by (type, canonical content) unless the
  window is ``ordered``.

Everything here operates on plain dicts so it is testable without pylmcp.
A *record* (captured message) is::

    {"address": str, "descriptor": str, "content_type": str,
     "source_group": str, "source_entity_id": int, "source_service_id": int,
     "type": "afrl.cmasi.KeyValuePair", "fields": {...}, "t": float}
"""
import copy
import json
import math
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_STRIP_FIELDS = (
    "Time", "TimeSent", "ReportedTime", "VehicleTime", "ScenarioTime",
    "TimeLastSeen", "TimeTaskCompleted", "TimeTaskActivated",
)
DEFAULT_RENUMBER_FIELDS = ("CommandID",)
DEFAULT_STRIP_HEADER = ("source_service_id",)
HEADER_KEYS = ("address", "content_type", "source_group", "source_entity_id")


class NormaliserConfig:
    """Normalisation options (scenario key ``normalise``)."""

    def __init__(self,
                 strip_fields: Iterable[str] = (),
                 renumber_fields: Iterable[str] = (),
                 strip_header: Iterable[str] = (),
                 float_digits: int = 6,
                 ignore_types: Iterable[str] = (),
                 replace_defaults: bool = False,
                 service_names: Optional[Dict[str, str]] = None):
        if replace_defaults:
            self.strip_fields = set(strip_fields)
            self.renumber_fields = set(renumber_fields)
            self.strip_header = set(strip_header)
        else:
            self.strip_fields = set(DEFAULT_STRIP_FIELDS) | set(strip_fields)
            self.renumber_fields = (set(DEFAULT_RENUMBER_FIELDS) |
                                    set(renumber_fields))
            self.strip_header = set(DEFAULT_STRIP_HEADER) | set(strip_header)
        self.float_digits = int(float_digits)
        self.ignore_types = set(ignore_types)
        self.service_names = dict(service_names or {})

    @classmethod
    def from_dict(cls, d: Dict[str, Any],
                  service_names: Optional[Dict[str, str]] = None):
        allowed = {"strip_fields", "renumber_fields", "strip_header",
                   "float_digits", "ignore_types", "replace_defaults"}
        unknown = set(d) - allowed
        if unknown:
            raise ValueError("unknown normalise option(s): %s" %
                             sorted(unknown))
        return cls(service_names=service_names, **d)

    def fingerprint(self) -> Dict[str, Any]:
        """JSON-able description (stored in goldens)."""
        return {"strip_fields": sorted(self.strip_fields),
                "renumber_fields": sorted(self.renumber_fields),
                "strip_header": sorted(self.strip_header),
                "float_digits": self.float_digits,
                "ignore_types": sorted(self.ignore_types)}


def short_type(full: str) -> str:
    """``afrl.cmasi.KeyValuePair`` -> ``KeyValuePair``."""
    return full.rsplit(".", 1)[-1]


def type_matches(name: str, patterns: Iterable[str]) -> bool:
    """True if ``name`` equals a pattern (full or short name)."""
    s = short_type(name)
    return any(p == name or p == s for p in patterns)


def _round_float(x: float, digits: int):
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "+Inf" if x > 0 else "-Inf"
    if x == 0:
        return 0.0
    return float("%.*g" % (digits, x))


def canonical_value(v: Any, cfg: NormaliserConfig, renumber: bool = True):
    """Recursively canonicalise a decoded field value."""
    if isinstance(v, dict):
        return {k: canonical_value(x, cfg, renumber)
                for k, x in sorted(v.items())
                if k not in cfg.strip_fields}
    if isinstance(v, (list, tuple)):
        return [canonical_value(x, cfg, renumber) for x in v]
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return _round_float(v, cfg.float_digits)
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    # Unknown type (e.g. enum): fall back to its string form
    return str(v)


class IdRenumberer:
    """Replace generated ids by their order of first occurrence."""

    def __init__(self, fields: Iterable[str]):
        self.fields = set(fields)
        self.maps: Dict[str, Dict[Any, str]] = {}

    def _label(self, field: str, value: Any) -> str:
        m = self.maps.setdefault(field, {})
        key = json.dumps(value, sort_keys=True)
        if key not in m:
            m[key] = "<%s#%d>" % (field, len(m) + 1)
        return m[key]

    def apply(self, v: Any) -> Any:
        if isinstance(v, dict):
            out = {}
            for k in sorted(v):
                if k in self.fields and not isinstance(v[k], (dict, list)):
                    out[k] = self._label(k, v[k])
                elif k in self.fields and isinstance(v[k], list):
                    out[k] = [self._label(k, x) if not isinstance(
                        x, (dict, list)) else self.apply(x) for x in v[k]]
                else:
                    out[k] = self.apply(v[k])
            return out
        if isinstance(v, list):
            return [self.apply(x) for x in v]
        return v


def _mask(v: Any, fields: Iterable[str]) -> Any:
    """Copy of v with renumbered fields masked (stable sort key input)."""
    fields = set(fields)
    if isinstance(v, dict):
        return {k: ("<id>" if k in fields and
                    not isinstance(x, (dict, list)) else _mask(x, fields))
                for k, x in v.items()}
    if isinstance(v, list):
        return [_mask(x, fields) for x in v]
    return v


def canonicalise_record(rec: Dict[str, Any],
                        cfg: NormaliserConfig) -> Dict[str, Any]:
    """Canonicalise one captured record (without id renumbering)."""
    out: Dict[str, Any] = {"type": rec["type"]}
    for k in HEADER_KEYS:
        if k not in cfg.strip_header and k in rec:
            out[k] = rec[k]
    sid = str(rec.get("source_service_id", ""))
    if "source_service_id" not in cfg.strip_header:
        out["source_service_id"] = rec.get("source_service_id")
    out["service"] = cfg.service_names.get(sid)
    out["fields"] = canonical_value(rec.get("fields", {}), cfg)
    return out


def sort_key(msg: Dict[str, Any], cfg: NormaliserConfig):
    masked = _mask(msg, cfg.renumber_fields)
    return (msg["type"], json.dumps(masked, sort_keys=True))


def normalise_window(records: List[Dict[str, Any]],
                     cfg: NormaliserConfig,
                     ordered: bool = False,
                     types: Optional[List[str]] = None,
                     renumberer: Optional[IdRenumberer] = None
                     ) -> List[Dict[str, Any]]:
    """Normalise the records of one window into sorted canonical messages."""
    msgs = []
    for r in records:
        if type_matches(r["type"], cfg.ignore_types):
            continue
        if types is not None and not type_matches(r["type"], types):
            continue
        msgs.append(canonicalise_record(r, cfg))
    if not ordered:
        msgs.sort(key=lambda m: sort_key(m, cfg))
    if renumberer is None:
        renumberer = IdRenumberer(cfg.renumber_fields)
    return [renumberer.apply(m) for m in msgs]


def normalise_capture(windows: Dict[str, List[Dict[str, Any]]],
                      cfg: NormaliserConfig,
                      window_opts: Optional[Dict[str, Dict[str, Any]]] = None
                      ) -> Dict[str, List[Dict[str, Any]]]:
    """Normalise every window; ids are renumbered across the whole capture.

    ``window_opts`` maps window name -> {"ordered": bool, "types": [...]}.
    Windows are processed in dict (= scenario) order.
    """
    window_opts = window_opts or {}
    ren = IdRenumberer(cfg.renumber_fields)
    out = {}
    for name, recs in windows.items():
        o = window_opts.get(name, {})
        out[name] = normalise_window(recs, cfg, ordered=o.get("ordered", False),
                                     types=o.get("types"), renumberer=ren)
    return out


def assign_windows(records: List[Dict[str, Any]],
                   boundaries: List[Any],
                   start_t: float,
                   capture_startup: bool = False
                   ) -> Dict[str, List[Dict[str, Any]]]:
    """Distribute timestamped records over windows.

    ``boundaries`` is an ordered list of ``(window_name, end_time)``.  A record
    belongs to the first window whose end time is >= its timestamp; records
    older than ``start_t`` go to ``__startup__`` (kept only if
    ``capture_startup``); records after the last boundary are returned in
    ``__trailing__``.  The result preserves arrival order inside a window.
    """
    out: Dict[str, List[Dict[str, Any]]] = {n: [] for n, _ in boundaries}
    startup: List[Dict[str, Any]] = []
    trailing: List[Dict[str, Any]] = []
    for r in sorted(records, key=lambda r: r["t"]):
        if r["t"] < start_t:
            startup.append(r)
            continue
        for name, end in boundaries:
            if r["t"] <= end:
                out[name].append(copy.copy(r))
                break
        else:
            trailing.append(r)
    result: Dict[str, List[Dict[str, Any]]] = {}
    if capture_startup:
        result["__startup__"] = startup
    result.update(out)
    result["__trailing__"] = trailing
    return result
