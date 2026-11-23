"""Canonicalisation of captured LMCP messages (design option 1).

A captured message is a plain dict::

    {"t_ms": 12.5, "address": "...", "descriptor": "afrl.cmasi.KeyValuePair",
     "content_type": "lmcp", "source_group": "", "source_entity_id": 100,
     "source_service_id": 0, "obj": {...decoded fields...}}

Canonicalisation:
  * drops transport noise (``t_ms``, optionally source entity/service ids);
  * strips configured field names (timestamps, volatile ids) at any depth;
  * remaps configured id fields to ordinals in order of first appearance so
    that cross-references stay consistent but concrete values do not matter;
  * rounds floats;
  * sorts by (descriptor, content) within a window (the whole capture by
    default, or fixed ``sort_window_ms`` buckets of arrival time).
"""
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_STRIP_FIELDS = ("Time", "TimeStamp", "Timestamp", "timestamp")


@dataclass
class CanonConfig:
    strip_fields: List[str] = field(
        default_factory=lambda: list(DEFAULT_STRIP_FIELDS))
    remap_fields: List[str] = field(default_factory=list)
    float_digits: int = 6
    sort_window_ms: Optional[float] = None
    strip_source_ids: bool = True
    keep_order_descriptors: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CanonConfig":
        data = dict(data or {})
        known = {"strip_fields", "remap_fields", "float_digits",
                 "sort_window_ms", "strip_source_ids",
                 "keep_order_descriptors"}
        unknown = set(data) - known
        if unknown:
            raise ValueError("unknown canonical keys: %s" % sorted(unknown))
        cfg = cls()
        for k, v in data.items():
            setattr(cfg, k, v)
        return cfg


class _Remapper:
    def __init__(self, fields):
        self.fields = set(fields)
        self.tables: Dict[str, Dict[Any, int]] = {}

    def map(self, name, value):
        table = self.tables.setdefault(name, {})
        key = json.dumps(value, sort_keys=True)
        if key not in table:
            table[key] = len(table)
        return "<%s#%d>" % (name, table[key])


def _norm_value(value, cfg: CanonConfig, remap: _Remapper):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in cfg.strip_fields:
                continue
            if k in remap.fields and not isinstance(v, (dict, list)):
                out[k] = remap.map(k, v)
            elif k in remap.fields and isinstance(v, list):
                out[k] = [remap.map(k, e) for e in v]
            else:
                out[k] = _norm_value(v, cfg, remap)
        return out
    if isinstance(value, (list, tuple)):
        return [_norm_value(v, cfg, remap) for v in value]
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        r = round(value, cfg.float_digits)
        return 0.0 if r == 0 else r  # fold -0.0
    if isinstance(value, bytes):
        return value.hex()
    return value


def sort_key(msg: Dict[str, Any]) -> str:
    return msg["descriptor"] + "\0" + json.dumps(
        msg.get("obj"), sort_keys=True, separators=(",", ":"))


def canonicalise(messages: List[Dict[str, Any]],
                 cfg: Optional[CanonConfig] = None) -> List[Dict[str, Any]]:
    """Return the canonical form of a capture (list of dicts, sorted)."""
    cfg = cfg or CanonConfig()
    remap = _Remapper(cfg.remap_fields)
    # remapping must see messages in arrival order so ordinals are stable
    ordered = sorted(messages, key=lambda m: m.get("t_ms", 0.0))
    entries = []
    for m in ordered:
        entry = {
            "descriptor": m["descriptor"],
            "content_type": m.get("content_type", "lmcp"),
            "obj": _norm_value(m.get("obj"), cfg, remap),
        }
        if not cfg.strip_source_ids:
            entry["source_entity_id"] = m.get("source_entity_id")
            entry["source_service_id"] = m.get("source_service_id")
        entry["_t"] = m.get("t_ms", 0.0)
        entries.append(entry)

    if cfg.sort_window_ms:
        t0 = entries[0]["_t"] if entries else 0.0
        buckets: Dict[int, List[Dict[str, Any]]] = {}
        for e in entries:
            buckets.setdefault(int((e["_t"] - t0) // cfg.sort_window_ms),
                               []).append(e)
        groups = [buckets[k] for k in sorted(buckets)]
    else:
        groups = [entries] if entries else []

    result: List[Dict[str, Any]] = []
    for g in groups:
        keep = [e for e in g if e["descriptor"] in cfg.keep_order_descriptors]
        if keep:
            # arrival order preserved for these descriptors; others sorted
            rest = sorted((e for e in g
                           if e["descriptor"] not in cfg.keep_order_descriptors),
                          key=sort_key)
            g = keep + rest
        else:
            g = sorted(g, key=sort_key)
        result.extend(g)
    for e in result:
        del e["_t"]
    return result


def filter_capture(messages, include=(), exclude=()):
    """Apply descriptor include/exclude globs (fnmatch) to a capture."""
    from fnmatch import fnmatch
    out = []
    for m in messages:
        d = m["descriptor"]
        if include and not any(fnmatch(d, p) for p in include):
            continue
        if any(fnmatch(d, p) for p in exclude):
            continue
        out.append(m)
    return out
