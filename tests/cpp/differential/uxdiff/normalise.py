"""Canonicalisation of captured LMCP traffic (Design decision 1, approach 1).

Pipeline for every captured raw bus message:

1. parse the envelope and the LMCP header (series / type id / version);
2. decode the fields (native decoder -> pylmcp if importable -> raw hex);
3. strip volatile fields (timestamps, ...), round floats;
4. sort records by (window, type, canonical content);
5. renumber correlation ids by first appearance in the sorted order, so
   request/response linkage is preserved but concrete id values are not.

Addresses, source service ids and arrival times are dropped altogether.
"""

import json

from . import lmcp

DEFAULT_STRIP_FIELDS = ("Time", "TimeStamp", "Timestamp", "TimeReceived",
                        "TimeSent")
DEFAULT_ID_FIELDS = ("RequestID", "ResponseID", "CorrelationID",
                     "TaskRequestID", "PlanningStateID")

_NATIVE_DECODERS = {}


def register_decoder(series, type_id, func):
    """Register ``func(body_bytes) -> dict`` for a message type.

    Native decoders take precedence over pylmcp and make the harness usable
    without e3/pylmcp for the types they cover.
    """
    _NATIVE_DECODERS[(series, type_id)] = func


def _decode_key_value_pair(body):
    r = lmcp.Reader(body)
    out = {"Key": r.string(), "Value": r.string()}
    if not r.at_end:
        raise lmcp.LmcpError("trailing bytes in KeyValuePair")
    return out


register_decoder(lmcp.CMASI, lmcp.KEY_VALUE_PAIR_ID, _decode_key_value_pair)

_pylmcp_state = {"tried": False, "mod": None}


def _pylmcp():
    """Lazily import pylmcp (needs e3); return None when unavailable."""
    if not _pylmcp_state["tried"]:
        _pylmcp_state["tried"] = True
        try:
            import os
            import sys
            here = os.path.dirname(os.path.abspath(__file__))
            cand = os.path.normpath(os.path.join(here, "..", ".."))
            if cand not in sys.path:
                sys.path.append(cand)
            import pylmcp
            from pylmcp.util import Buffer
            _pylmcp_state["mod"] = (pylmcp, Buffer)
        except Exception:  # ImportError for pylmcp or e3
            _pylmcp_state["mod"] = None
    return _pylmcp_state["mod"]


def decode_fields(frame_bytes, frame):
    """Return (fields_dict | None, error | None)."""
    func = _NATIVE_DECODERS.get((frame.series, frame.type_id))
    if func is not None:
        try:
            return func(frame.body), None
        except lmcp.LmcpError as exc:
            return None, str(exc)
    mod = _pylmcp()
    if mod is not None:
        pylmcp, Buffer = mod
        try:
            obj = pylmcp.Object.unpack(Buffer(frame_bytes[lmcp.HEADER_LEN:]))
            if obj is not None:
                return obj.as_dict(), None
        except Exception as exc:  # unknown type, truncated data, ...
            return None, "pylmcp decode failed: %s" % exc
    return None, None


class Captured(object):
    """A raw captured bus message with harness-side metadata."""

    def __init__(self, raw, t_ms=0.0, step=0):
        self.raw = bytes(raw)
        self.t_ms = t_ms
        self.step = step


def _round(value, digits):
    if isinstance(value, float):
        return round(value, digits) + 0.0
    if isinstance(value, list):
        return [_round(v, digits) for v in value]
    if isinstance(value, dict):
        return {k: _round(v, digits) for k, v in value.items()}
    return value


def _strip(value, names):
    if isinstance(value, dict):
        return {k: _strip(v, names) for k, v in value.items() if k not in names}
    if isinstance(value, list):
        return [_strip(v, names) for v in value]
    return value


def _blank_and_collect(value, id_fields, collected):
    """Replace id values by a placeholder; collect them in visiting order."""
    if isinstance(value, dict):
        out = {}
        for k in sorted(value):
            v = value[k]
            if k in id_fields and not isinstance(v, (dict, list)):
                out[k] = "<id>"
                collected.append((k, v))
            elif k in id_fields and isinstance(v, list):
                out[k] = ["<id>"] * len(v)
                collected.extend((k, x) for x in v)
            else:
                out[k] = _blank_and_collect(v, id_fields, collected)
        return out
    if isinstance(value, list):
        return [_blank_and_collect(v, id_fields, collected) for v in value]
    return value


def _remap(value, id_fields, mapping):
    if isinstance(value, dict):
        out = {}
        for k in sorted(value):
            v = value[k]
            if k in id_fields and isinstance(v, list):
                out[k] = [mapping[(k, x)] for x in v]
            elif k in id_fields and not isinstance(v, dict):
                out[k] = mapping[(k, v)]
            else:
                out[k] = _remap(v, id_fields, mapping)
        return out
    if isinstance(value, list):
        return [_remap(v, id_fields, mapping) for v in value]
    return value


def dumps(obj):
    """Deterministic JSON text."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class Normaliser(object):
    """Turns captured raw messages into canonical, comparable records."""

    def __init__(self, strip_fields=None, id_fields=None, float_digits=6,
                 window="all", keep_entity_id=False, exclude_types=(),
                 exclude_raw=()):
        self.strip_fields = set(DEFAULT_STRIP_FIELDS if strip_fields is None
                                else strip_fields)
        self.id_fields = set(DEFAULT_ID_FIELDS if id_fields is None
                             else id_fields)
        self.float_digits = float_digits
        if window not in ("all", "step"):
            raise ValueError("window must be 'all' or 'step'")
        self.window = window
        self.keep_entity_id = keep_entity_id
        self.exclude_types = set(exclude_types)
        self.exclude_raw = set(bytes(x) for x in exclude_raw)

    @classmethod
    def from_options(cls, opts, exclude_raw=()):
        opts = dict(opts or {})
        return cls(strip_fields=opts.get("strip_fields"),
                   id_fields=opts.get("id_fields"),
                   float_digits=opts.get("float_digits", 6),
                   window=opts.get("window", "all"),
                   keep_entity_id=opts.get("keep_entity_id", False),
                   exclude_types=opts.get("exclude_types", ()),
                   exclude_raw=exclude_raw)

    def _one(self, cap):
        window = cap.step if self.window == "step" else 0
        try:
            env = lmcp.parse_envelope(cap.raw)
        except lmcp.LmcpError as exc:
            return {"window": window, "malformed": "envelope: %s" % exc,
                    "raw": cap.raw.hex()}
        if env.payload in self.exclude_raw:
            return None
        try:
            frame = lmcp.parse_frame(env.payload)
        except lmcp.LmcpError as exc:
            return {"window": window, "malformed": "frame: %s" % exc,
                    "descriptor": env.descriptor, "raw": env.payload.hex()}
        rec = {
            "window": window,
            "series": frame.series,
            "type_id": frame.type_id,
            "version": frame.version,
            "descriptor": env.descriptor,
            "content_type": env.content_type,
        }
        if self.keep_entity_id:
            rec["source_entity_id"] = env.source_entity_id
        fields, err = decode_fields(env.payload, frame)
        if err:
            rec["decode_error"] = err
        if fields is not None:
            fields = _round(_strip(fields, self.strip_fields),
                            self.float_digits)
            rec["fields"] = fields
        else:
            rec["raw_body"] = frame.body.hex()
        return rec

    def normalise(self, captured):
        """Return the canonical list of records (sorted, ids renumbered)."""
        recs = []
        for cap in captured:
            rec = self._one(cap)
            if rec is None:
                continue
            if rec.get("descriptor") in self.exclude_types or \
                    ("series" in rec and
                     "%s/%d" % (rec["series"], rec["type_id"])
                     in self.exclude_types):
                continue
            recs.append(rec)

        # Sort key ignores concrete id values.
        keyed = []
        for rec in recs:
            collected = []
            blank = dict(rec)
            if "fields" in blank:
                blank["fields"] = _blank_and_collect(
                    blank["fields"], self.id_fields, collected)
            keyed.append((dumps(blank), rec, collected))
        keyed.sort(key=lambda t: (t[1]["window"], t[0]))

        mapping = {}
        counters = {}
        out = []
        for _, rec, collected in keyed:
            for name, val in collected:
                if (name, val) not in mapping:
                    counters[name] = counters.get(name, 0) + 1
                    mapping[(name, val)] = "%s#%d" % (name, counters[name])
            if "fields" in rec:
                rec = dict(rec)
                rec["fields"] = _remap(rec["fields"], self.id_fields, mapping)
            out.append(rec)
        return out
