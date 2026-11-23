"""Canonicalisation of captured LMCP messages.

A *captured message* is a plain dict::

    {"t_ms": 12.0, "address": "...", "descriptor": "afrl.cmasi.KeyValuePair",
     "source_group": "", "source_entity_id": 100, "source_service_id": 3,
     "obj": {...decoded LMCP fields...}}

``canonicalise`` turns a capture into windows of canonical messages.
"""
import json
import re

# Field names (case-insensitive, full match) whose values are run-specific
# timestamps and are dropped.
DEFAULT_STRIP_FIELDS = [
    r"time", r"timestamp", r".*_?timestamp", r"timeofcreation", r"creationtime",
    r"time_?ms", r"time_?s", r"timestamp_?ms", r"timestamp_?s", r"timeusec",
    r"currenttime", r"scenariotime", r"timestamps",
]

# Fields holding message/request ids.  They are renumbered by order of first
# appearance (see README) so that cross-message references stay checked.
DEFAULT_ID_FIELDS = [
    r"requestid", r"responseid", r"uniqueautomationrequestid",
    r"planrequestid", r"taskrequestid", r"taskplanoptionsid", r"corresponding\w*id",
    r"planid", r"assignmentid", r"summaryid", r"originalrequestid",
]


class Options(object):
    def __init__(self, strip_fields=None, id_fields=None, id_mode="renumber",
                 window_ms=200.0, float_digits=6, ignore_header=None,
                 extra_strip_fields=(), extra_id_fields=()):
        if id_mode not in ("renumber", "strip", "keep"):
            raise ValueError("id_mode must be renumber|strip|keep")
        self.strip_fields = list(strip_fields if strip_fields is not None
                                 else DEFAULT_STRIP_FIELDS) + list(extra_strip_fields)
        self.id_fields = list(id_fields if id_fields is not None
                              else DEFAULT_ID_FIELDS) + list(extra_id_fields)
        self.id_mode = id_mode
        if window_ms is not None and (isinstance(window_ms, bool) or window_ms < 0):
            raise ValueError("window_ms must be >= 0 or null")
        self.window_ms = window_ms
        self.float_digits = float_digits
        # Header attributes ignored in comparison.  source_service_id is
        # assigned per-process so it is ignored by default.
        self.ignore_header = list(ignore_header if ignore_header is not None
                                  else ["source_service_id"])
        # Compile (raises re.error, which is a ValueError-ish for callers)
        try:
            self._strip = [re.compile(p, re.I) for p in self.strip_fields]
            self._ids = [re.compile(p, re.I) for p in self.id_fields]
        except re.error as e:
            raise ValueError("bad regex: %s" % e)

    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        allowed = {"strip_fields", "id_fields", "id_mode", "window_ms",
                   "float_digits", "ignore_header", "extra_strip_fields",
                   "extra_id_fields"}
        unknown = set(d) - allowed
        if unknown:
            raise ValueError("unknown normalization keys: %s" % ", ".join(sorted(unknown)))
        return cls(**d)

    def is_strip(self, name):
        return any(r.fullmatch(name) for r in self._strip)

    def is_id(self, name):
        return any(r.fullmatch(name) for r in self._ids)


class Canonical(object):
    """A canonical message: type, header and normalised body."""

    def __init__(self, type_name, header, body, t_ms=0.0):
        self.type = type_name
        self.header = header
        self.body = body
        self.t_ms = t_ms

    def key(self):
        return json.dumps([self.type, self.header, self.body], sort_keys=True,
                          separators=(",", ":"))

    def as_dict(self):
        return {"type": self.type, "header": self.header, "body": self.body}

    def __eq__(self, other):
        return isinstance(other, Canonical) and self.key() == other.key()

    def __hash__(self):
        return hash(self.key())

    def __repr__(self):
        return "Canonical(%s)" % self.key()


class IdRenumberer(object):
    """Maps raw id values to ``<id:N>`` placeholders, per stream, in order of
    first appearance.  Zero is kept as-is (conventionally 'unset')."""

    def __init__(self):
        self.maps = {}

    def map(self, name, value):
        if value in (0, None):
            return value
        table = self.maps.setdefault(name.lower(), {})
        key = json.dumps(value, sort_keys=True)
        if key not in table:
            table[key] = len(table) + 1
        return "<id:%d>" % table[key]


def _norm_float(v, digits):
    if digits is None or v != v or v in (float("inf"), float("-inf")):
        return v
    r = round(v, digits)
    return 0.0 if r == 0 else r  # fold -0.0


def normalize_value(name, value, opts, ids):
    """Recursively normalise ``value`` found under field ``name``."""
    if isinstance(value, dict):
        return normalize_obj(value, opts, ids)
    if isinstance(value, (list, tuple)):
        return [normalize_value(name, v, opts, ids) for v in value]
    if isinstance(value, float):
        return _norm_float(value, opts.float_digits)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


def normalize_obj(obj, opts, ids):
    out = {}
    for k in sorted(obj):
        v = obj[k]
        if opts.is_strip(k):
            continue
        if opts.is_id(k) and opts.id_mode != "keep":
            if opts.id_mode == "strip":
                continue
            if isinstance(v, (list, tuple)):
                out[k] = [ids.map(k, x) for x in v]
            elif isinstance(v, (int, str)):
                out[k] = ids.map(k, v)
            else:
                out[k] = normalize_value(k, v, opts, ids)
            continue
        out[k] = normalize_value(k, v, opts, ids)
    return out


def canonicalise_message(raw, opts, ids):
    header = {}
    for k in ("address", "content_type", "source_group", "source_entity_id",
              "source_service_id"):
        if k in raw and k not in opts.ignore_header:
            header[k] = raw[k]
    type_name = raw.get("descriptor") or raw.get("address") or ""
    body = normalize_obj(raw.get("obj") or {}, opts, ids)
    return Canonical(type_name, header, body, raw.get("t_ms", 0.0))


def window_messages(msgs, window_ms):
    """Split time-ordered messages into windows.

    A new window starts when the gap to the previous message exceeds
    ``window_ms``.  ``window_ms is None`` puts everything in one window;
    ``0`` makes every message its own window (strict arrival order).
    """
    if not msgs:
        return []
    if window_ms is None:
        return [list(msgs)]
    windows = [[msgs[0]]]
    for prev, m in zip(msgs, msgs[1:]):
        if window_ms == 0 or m.t_ms - prev.t_ms > window_ms:
            windows.append([])
        windows[-1].append(m)
    return windows


def canonicalise(raw_msgs, opts=None):
    """Canonicalise a captured stream into a list of windows.

    1. Order by capture time and group into windows (see ``window_messages``).
    2. Inside each window sort by (type, body-with-ids-stripped), so that
       legitimate reordering does not produce a diff.
    3. Normalise the final bodies, renumbering ids in that sorted order so
       the placeholders do not depend on arrival order.
    """
    opts = opts or Options()
    strip_opts = Options.from_dict({
        "strip_fields": opts.strip_fields, "id_fields": opts.id_fields,
        "id_mode": "strip" if opts.id_mode != "keep" else "keep",
        "window_ms": opts.window_ms, "float_digits": opts.float_digits,
        "ignore_header": opts.ignore_header})
    ordered = sorted(raw_msgs, key=lambda m: m.get("t_ms", 0.0))
    probe = [canonicalise_message(m, strip_opts, IdRenumberer()) for m in ordered]
    pairs = list(zip(ordered, probe))
    for p in pairs:
        p[1].t_ms = p[0].get("t_ms", 0.0)
    wins = window_messages([p[1] for p in pairs], opts.window_ms)
    by_probe = {id(p[1]): p[0] for p in pairs}
    ids = IdRenumberer()
    result = []
    for w in wins:
        if opts.window_ms != 0:
            w = sorted(w, key=lambda c: (c.type, c.key()))
        result.append([canonicalise_message(by_probe[id(c)], opts, ids) for c in w])
    return result
