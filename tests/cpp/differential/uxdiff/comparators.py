"""Comparators (Design decision 1, approach 2: per-service plug-ins).

A comparator receives the canonical record lists of the reference (Ada) and
candidate (C++) runs and returns a :class:`DiffReport`.  Register custom ones
with :func:`register_comparator`; select with ``"comparator": "<name>"`` in a
scenario.  Plug-in modules are loaded with ``--plugin`` or the scenario's
``"plugins"`` list and just call :func:`register_comparator` at import time.
"""

import difflib
import importlib
import importlib.util
import os
import sys

from .normalise import dumps


class DiffEntry(object):
    """One difference: kind is 'missing' (ref only), 'extra' (cand only)."""

    def __init__(self, kind, ref=None, cand=None):
        self.kind = kind
        self.ref = ref
        self.cand = cand

    def as_dict(self):
        return {"kind": self.kind, "ref": self.ref, "cand": self.cand}


class DiffReport(object):
    def __init__(self, entries, ref_count, cand_count, comparator):
        self.entries = list(entries)
        self.ref_count = ref_count
        self.cand_count = cand_count
        self.comparator = comparator

    @property
    def equal(self):
        return not self.entries

    def as_dict(self):
        return {"equal": self.equal, "comparator": self.comparator,
                "ref_count": self.ref_count, "cand_count": self.cand_count,
                "differences": [e.as_dict() for e in self.entries]}

    def format(self):
        head = "comparator=%s reference=%d candidate=%d: %s" % (
            self.comparator, self.ref_count, self.cand_count,
            "MATCH" if self.equal else "%d difference(s)" % len(self.entries))
        lines = [head]
        for e in self.entries:
            if e.kind == "missing":
                lines.append("  - missing in candidate: %s" % dumps(e.ref))
            elif e.kind == "extra":
                lines.append("  + extra in candidate:   %s" % dumps(e.cand))
            else:
                lines.append("  ~ changed:")
                lines.append("      ref:  %s" % dumps(e.ref))
                lines.append("      cand: %s" % dumps(e.cand))
        return "\n".join(lines)


def diff_records(ref, cand, comparator="default"):
    """Align two canonical (sorted) record lists and report differences."""
    a = [dumps(r) for r in ref]
    b = [dumps(r) for r in cand]
    entries = []
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        n = max(i2 - i1, j2 - j1)
        for k in range(n):
            r = ref[i1 + k] if i1 + k < i2 else None
            c = cand[j1 + k] if j1 + k < j2 else None
            if r is not None and c is not None:
                entries.append(DiffEntry("changed", r, c))
            elif r is not None:
                entries.append(DiffEntry("missing", ref=r))
            else:
                entries.append(DiffEntry("extra", cand=c))
    return DiffReport(entries, len(ref), len(cand), comparator)


class Comparator(object):
    """Base class.  Override :meth:`select`, :meth:`project`, :meth:`compare`.

    ``options`` is the scenario's ``comparator_options`` dict.
    """

    name = "base"

    def __init__(self, options=None):
        self.options = dict(options or {})

    def select(self, record):
        """Return True to keep ``record`` in the comparison."""
        return True

    def project(self, record):
        """Return the comparable view of a kept record."""
        return record

    def sort_key(self, record):
        return (record.get("window", 0), dumps(record))

    def prepare(self, records):
        out = [self.project(r) for r in records if self.select(r)]
        out.sort(key=self.sort_key)
        return out

    def compare(self, ref_records, cand_records):
        ref = self.prepare(ref_records)
        cand = self.prepare(cand_records)
        return diff_records(ref, cand, self.name)


class DefaultComparator(Comparator):
    """Strict canonical comparison of every captured message.

    Options: ``include_types`` / ``exclude_types`` (lists of descriptors).
    """

    name = "default"

    def select(self, record):
        d = record.get("descriptor")
        inc = self.options.get("include_types")
        exc = self.options.get("exclude_types", ())
        if inc and d not in inc:
            return False
        return d not in exc


class HeartbeatComparator(Comparator):
    """Compares only KeyValuePair messages as a multiset of (Key, Value).

    Options: ``keys`` (only these keys), ``compare_values`` (default True),
    ``ignore_count`` (compare sets instead of multisets, default False).
    """

    name = "heartbeat"

    def select(self, record):
        if record.get("series") != "CMASI" or record.get("type_id") != 2:
            return False
        keys = self.options.get("keys")
        fields = record.get("fields") or {}
        return not keys or fields.get("Key") in keys

    def project(self, record):
        fields = record.get("fields") or {}
        out = {"window": record.get("window", 0), "Key": fields.get("Key"),
               "type": "KeyValuePair"}
        if self.options.get("compare_values", True):
            out["Value"] = fields.get("Value")
        if "raw_body" in record:
            out["raw_body"] = record["raw_body"]
        return out

    def prepare(self, records):
        out = super().prepare(records)
        if self.options.get("ignore_count"):
            seen, uniq = set(), []
            for r in out:
                k = dumps(r)
                if k not in seen:
                    seen.add(k)
                    uniq.append(r)
            out = uniq
        return out


_REGISTRY = {}


def register_comparator(name_or_cls, cls=None):
    """Register a comparator class.

    Usable as ``register_comparator("svc", Cls)``, ``register_comparator(Cls)``
    (uses ``Cls.name``) or as a decorator ``@register_comparator("svc")``.
    """
    if cls is None and isinstance(name_or_cls, str):
        def deco(c):
            register_comparator(name_or_cls, c)
            return c
        return deco
    if cls is None:
        cls, name_or_cls = name_or_cls, name_or_cls.name
    if not (isinstance(cls, type) and issubclass(cls, Comparator)):
        raise TypeError("comparator must subclass Comparator")
    cls.name = name_or_cls
    _REGISTRY[name_or_cls] = cls
    return cls


def get_comparator(name, options=None):
    try:
        return _REGISTRY[name](options)
    except KeyError:
        raise KeyError("unknown comparator %r (known: %s)" %
                       (name, ", ".join(sorted(_REGISTRY))))


def list_comparators():
    return sorted(_REGISTRY)


def load_plugin(spec):
    """Import a plug-in given a file path (``*.py``) or module name."""
    if spec.endswith(".py") or os.sep in spec:
        path = os.path.abspath(spec)
        modname = "uxdiff_plugin_" + os.path.splitext(os.path.basename(path))[0]
        s = importlib.util.spec_from_file_location(modname, path)
        if s is None or s.loader is None:
            raise ImportError("cannot load plug-in %s" % spec)
        mod = importlib.util.module_from_spec(s)
        sys.modules[modname] = mod
        s.loader.exec_module(mod)
        return mod
    return importlib.import_module(spec)


register_comparator("default", DefaultComparator)
register_comparator("heartbeat", HeartbeatComparator)
