"""Canonicalisation of captured records.

Design decision: both implementations are compared after *canonicalisation*
rather than byte-for-byte:

* volatile fields are removed (timestamps, entity-id-time fields, envelope
  source service id, ...);
* generated identifiers that must merely be *consistent* are renumbered by
  order of appearance (``<id1>``, ``<id2>``...) so correlation is checked
  but not the concrete value;
* floats are rounded;
* records are bucketed into time windows and sorted inside each window by
  (type, canonical content) so that cross-thread ordering differences between
  the two binaries do not matter.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_STRIP_FIELDS = [
    r"^(?i:time|timestamp|time_?stamp|entityidtime|.*timestamp|"
    r".*_?time_?ms|.*entityidtime)$",
]
DEFAULT_REMAP_FIELDS = ["ResponseID", "CommandID", "PlanID"]
DEFAULT_STRIP_ENVELOPE = ["source_service_id", "t_ms", "source_group"]
ENVELOPE_KEYS = ("address", "descriptor", "content_type", "source_group",
                 "source_entity_id", "source_service_id")


@dataclass
class NormaliseOptions:
    strip_fields: List[str] = field(
        default_factory=lambda: list(DEFAULT_STRIP_FIELDS))
    extra_strip_fields: List[str] = field(default_factory=list)
    remap_fields: List[str] = field(
        default_factory=lambda: list(DEFAULT_REMAP_FIELDS))
    strip_envelope: List[str] = field(
        default_factory=lambda: list(DEFAULT_STRIP_ENVELOPE))
    float_digits: int = 6
    window_ms: int = 0          # 0 => a single window
    sort: bool = True
    ignore_types: List[str] = field(default_factory=list)

    @classmethod
    def from_options(cls, options: Optional[Dict[str, Any]]
                     ) -> "NormaliseOptions":
        options = dict(options or {})
        known = set(cls.__dataclass_fields__)
        unknown = set(options) - known
        if unknown:
            raise ValueError("unknown normaliser options: %s"
                             % sorted(unknown))
        return cls(**options)

    def strip_regexes(self):
        return [re.compile(p)
                for p in self.strip_fields + self.extra_strip_fields]


ID_PLACEHOLDER = "<id>"


def _clean(value: Any, opts: NormaliseOptions, strip, remap_fields,
           remapped: Optional[Dict[Tuple[str, Any], str]]) -> Any:
    """Recursively canonicalise. When ``remapped`` is None, ids become the
    neutral placeholder (used to compute the sort key)."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "$type":
                out[k] = v
                continue
            if any(r.match(k) for r in strip):
                continue
            if k in remap_fields and v not in (None, 0, "", []):
                if remapped is None:
                    out[k] = ID_PLACEHOLDER
                else:
                    out[k] = remapped.setdefault(
                        (k, v), "<id%d>" % (len(remapped) + 1))
                continue
            out[k] = _clean(v, opts, strip, remap_fields, remapped)
        return out
    if isinstance(value, list):
        return [_clean(v, opts, strip, remap_fields, remapped)
                for v in value]
    if isinstance(value, float):
        r = round(value, opts.float_digits)
        return 0.0 if r == 0 else r        # fold -0.0
    return value


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def normalise(records: Iterable[Dict[str, Any]],
              options: Optional[NormaliseOptions] = None
              ) -> List[Dict[str, Any]]:
    """Canonicalise ``records`` and return a list of normalised messages.

    Each result is ``{"window": int, "type": str, "envelope": {...},
    "obj": {...}}`` ordered by window, then by (type, content).
    """
    opts = options or NormaliseOptions()
    strip = opts.strip_regexes()
    remap_fields = set(opts.remap_fields)

    staged = []
    for rec in records:
        obj = rec.get("obj", {})
        mtype = obj.get("$type", rec.get("descriptor", ""))
        if mtype in opts.ignore_types:
            continue
        window = (int(rec.get("t_ms", 0)) // opts.window_ms
                  if opts.window_ms > 0 else 0)
        envelope = {k: rec[k] for k in ENVELOPE_KEYS
                    if k in rec and k not in opts.strip_envelope}
        neutral = _clean(obj, opts, strip, remap_fields, None)
        staged.append((window, mtype, dumps(envelope), dumps(neutral),
                       envelope, obj))

    if opts.sort:
        # sort is stable; ties keep arrival order (identical content anyway)
        staged.sort(key=lambda s: (s[0], s[1], s[2], s[3]))
    else:
        staged.sort(key=lambda s: s[0])

    remapped: Dict[Tuple[str, Any], str] = {}
    result = []
    for window, mtype, _e, _n, envelope, obj in staged:
        result.append({"window": window, "type": mtype, "envelope": envelope,
                       "obj": _clean(obj, opts, strip, remap_fields,
                                     remapped)})
    return _compact_windows(result)


def _compact_windows(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Renumber windows densely so empty windows never matter."""
    seen: Dict[int, int] = {}
    for m in msgs:
        m["window"] = seen.setdefault(m["window"], len(seen))
    return msgs
