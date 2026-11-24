"""Canonicalisation of captured messages (design decision 1, approach 1).

A capture record is a dict::

    {address, descriptor, content_type, source_group, source_entity_id,
     source_service_id, obj (decoded dict | None), raw_hex, step, t}

``step`` is the number of scenario messages already injected when the record
was received: it defines the *window* in which ordering is not significant.

Normalisation:

* drops volatile header/payload data (timestamps, service ids, raw bytes),
* masks or renumbers identifiers (``id_mode``: ``renumber`` | ``strip`` |
  ``keep``); renumbering keeps cross-message linkage (same id -> same token),
* sorts the messages of each window by (type, canonical content).
"""
import copy
import json
import re
from typing import Any, Dict, List

DEFAULT_TIME_KEYS = [
    r"(?i)^(time|timestamp|time_?stamp\w*|\w*_?timestamp\w*|"
    r"(creation|created|sent|received|last_?updated?)_?time\w*|\w*_ms|"
    r"\w*time_?stamp)$",
]
DEFAULT_ID_KEYS = [r"^(id|\w*_ids?|\w*(ID|Id)s?)$"]

DEFAULT_OPTIONS = {
    "window": "step",            # "step" | "all"
    "id_mode": "renumber",       # "renumber" | "strip" | "keep"
    "time_keys": DEFAULT_TIME_KEYS,
    "id_keys": DEFAULT_ID_KEYS,
    "ignore_keys": [],           # extra regexes of keys to drop entirely
    "ignore_types": [],          # descriptor globs dropped from comparison
    "keep_service_id": False,
    "keep_source_group": True,
    "float_digits": 6,
}


def options(overrides: Dict[str, Any] = None) -> Dict[str, Any]:
    opts = copy.deepcopy(DEFAULT_OPTIONS)
    opts.update(overrides or {})
    return opts


def _matches(key: str, patterns) -> bool:
    return any(re.match(p, key) for p in patterns)


def _canon_value(v, opts, idmap, mask):
    """Recursively canonicalise; ``idmap`` None means "mask only"."""
    if isinstance(v, dict):
        out = {}
        for k in sorted(v):
            if _matches(k, opts["time_keys"]) or \
                    _matches(k, opts["ignore_keys"]):
                continue
            x = v[k]
            if opts["id_mode"] != "keep" and _matches(k, opts["id_keys"]) \
                    and not isinstance(x, (dict,)):
                out[k] = _id_token(k, x, opts, idmap, mask)
            else:
                out[k] = _canon_value(x, opts, idmap, mask)
        return out
    if isinstance(v, list):
        return [_canon_value(x, opts, idmap, mask) for x in v]
    if isinstance(v, float):
        return round(v, opts["float_digits"])
    return v


def _id_token(key, x, opts, idmap, mask):
    if opts["id_mode"] == "strip" or mask:
        return "<id>"
    if isinstance(x, list):
        return [_id_token(key, e, opts, idmap, mask) for e in x]
    if isinstance(x, (int, str)) and not isinstance(x, bool):
        table = idmap.setdefault(key, {})
        return "<%s#%d>" % (key, table.setdefault(x, len(table)))
    return x


def _dump(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"))


def _type_ignored(descriptor, opts) -> bool:
    import fnmatch
    return any(fnmatch.fnmatchcase(descriptor, g) for g in opts["ignore_types"])


def normalise(records: List[dict], overrides: Dict[str, Any] = None) -> List[dict]:
    """Return the canonical, ordered list of messages.

    Each element: ``{"step", "type", "key", "msg"}`` where ``msg`` is the
    canonical dict and ``key`` its stable json (used for equality).
    """
    opts = options(overrides)
    entries = []
    for r in records:
        if _type_ignored(r.get("descriptor", ""), opts):
            continue
        step = 0 if opts["window"] == "all" else int(r.get("step", 0))
        header = {"descriptor": r.get("descriptor"),
                  "address": r.get("address"),
                  "content_type": r.get("content_type"),
                  "source_entity_id": r.get("source_entity_id")}
        if opts["keep_source_group"]:
            header["source_group"] = r.get("source_group")
        if opts["keep_service_id"]:
            header["source_service_id"] = r.get("source_service_id")
        obj = r.get("obj")
        if obj is None:  # undecodable: fall back to raw payload bytes
            body = {"_undecoded_payload": _payload_hex(r)}
        else:
            body = obj
        entries.append((step, header, body))

    # Sort on id-masked content first (id values may be implementation
    # specific), then number ids in that deterministic order.
    def sort_key(e):
        step, header, body = e
        return (step, header["descriptor"] or "",
                _dump(_canon_value(body, opts, None, True)),
                _dump(header))
    entries.sort(key=sort_key)

    idmap: Dict[str, Dict[Any, int]] = {}
    result = []
    for step, header, body in entries:
        msg = {"header": header, "body": _canon_value(body, opts, idmap, False)}
        result.append({"step": step, "type": header["descriptor"],
                       "key": _dump(msg), "msg": msg})
    return result


def _payload_hex(rec) -> str:
    raw = rec.get("raw_hex")
    if not raw:
        return ""
    data = bytes.fromhex(raw)
    parts = data.split(b"$", 2)
    return parts[2].hex() if len(parts) == 3 else raw
