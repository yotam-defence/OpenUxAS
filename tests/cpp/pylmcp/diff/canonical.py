"""Canonicalisation of decoded LMCP messages (design option 1).

Steps applied to every message:

1. drop timestamp-like and id-like fields (recursively), or, with
   ``id_mode='remap'``, replace ids by their first-appearance ordinal so
   cross references are still checked;
2. round floats to ``float_digits`` (NaN/inf made explicit);
3. drop envelope data that legitimately differs (service id; optionally
   source entity);
4. sort messages inside each window by (type, canonical JSON) so arrival
   order between concurrently running services is irrelevant.
"""
from __future__ import annotations

import fnmatch
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .messages import DecodedMessage

DEFAULT_STRIP_FIELDS = ["Time", "TimeStamp", "Timestamp", "*TimeStamp",
                        "*Timestamp", "LastTime"]
DEFAULT_ID_FIELDS = ["RequestID", "ResponseID", "TaskRequestID", "CommandID"]


@dataclass
class CanonSettings:
    strip_fields: List[str] = field(
        default_factory=lambda: list(DEFAULT_STRIP_FIELDS))
    id_fields: List[str] = field(
        default_factory=lambda: list(DEFAULT_ID_FIELDS))
    id_mode: str = "strip"
    float_digits: int = 6
    keep_service_id: bool = False
    keep_source_entity: bool = True

    @classmethod
    def from_scenario(cls, norm) -> "CanonSettings":
        s = cls()
        if norm.strip_fields is not None:
            s.strip_fields = list(norm.strip_fields)
        if norm.id_fields is not None:
            s.id_fields = list(norm.id_fields)
        s.id_mode = norm.id_mode
        s.float_digits = norm.float_digits
        s.keep_service_id = norm.keep_service_id
        s.keep_source_entity = norm.keep_source_entity
        return s


@dataclass
class CanonMessage:
    """A canonical message; ``key`` is its stable sortable serialisation."""
    type: str
    body: Dict[str, Any]
    window: int
    key: str = ""

    def dumps(self) -> str:
        return self.key


def _match(name: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


class _IdMapper:
    def __init__(self) -> None:
        self.maps: Dict[str, Dict[Any, int]] = {}

    def __call__(self, name: str, value: Any) -> str:
        m = self.maps.setdefault(name, {})
        k = json.dumps(value, sort_keys=True)
        if k not in m:
            m[k] = len(m) + 1
        return "<%s#%d>" % (name, m[k])


def _norm_value(v: Any, s: CanonSettings, idmap: Optional[_IdMapper]) -> Any:
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if _match(k, s.strip_fields):
                continue
            if _match(k, s.id_fields):
                if s.id_mode == "remap" and idmap is not None:
                    out[k] = _remap(x, k, idmap)
                continue
            out[k] = _norm_value(x, s, idmap)
        return out
    if isinstance(v, (list, tuple)):
        return [_norm_value(x, s, idmap) for x in v]
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        r = round(v, s.float_digits)
        return 0.0 if r == 0 else r        # normalise -0.0
    if isinstance(v, bytes):
        return v.hex()
    return v


def _remap(x: Any, name: str, idmap: _IdMapper) -> Any:
    if isinstance(x, list):
        return [idmap(name, e) for e in x]
    return idmap(name, x)


def canonicalise_message(msg: DecodedMessage, s: CanonSettings,
                         idmap: Optional[_IdMapper] = None) -> CanonMessage:
    body: Dict[str, Any] = {
        "content_type": msg.content_type,
        "source_group": msg.source_group,
        "fields": _norm_value(msg.fields, s, idmap),
    }
    if s.keep_source_entity:
        body["source_entity_id"] = msg.source_entity_id
    if s.keep_service_id:
        body["source_service_id"] = msg.source_service_id
    key = msg.type + " " + json.dumps(body, sort_keys=True,
                                      separators=(",", ":"))
    return CanonMessage(type=msg.type, body=body, window=msg.window, key=key)


def canonicalise(messages: List[DecodedMessage],
                 settings: Optional[CanonSettings] = None
                 ) -> Dict[int, List[CanonMessage]]:
    """Canonicalise and group by window; each window is sorted.

    In ``remap`` mode messages are first sorted using id-stripped keys so the
    ordinals assigned do not depend on arrival order.
    """
    s = settings or CanonSettings()
    windows: Dict[int, List[DecodedMessage]] = {}
    for m in messages:
        windows.setdefault(m.window, []).append(m)

    idmap = _IdMapper() if s.id_mode == "remap" else None
    if idmap is not None:
        stripped = CanonSettings(**{**vars(s), "id_mode": "strip"})
    result: Dict[int, List[CanonMessage]] = {}
    for w in sorted(windows):
        msgs = windows[w]
        if idmap is not None:
            msgs = sorted(msgs, key=lambda m: canonicalise_message(
                m, stripped).key)
        canon = [canonicalise_message(m, s, idmap) for m in msgs]
        canon.sort(key=lambda c: (c.type, c.key))
        result[w] = canon
    return result
