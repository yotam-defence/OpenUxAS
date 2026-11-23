"""Comparator registry and built-in comparators.

A comparator receives the two canonicalised streams (lists of windows of
:class:`normalize.Canonical`) and returns a list of
:class:`report.Difference`.  Write a plug-in by subclassing
:class:`Comparator` and decorating it with :func:`register`.
"""
import fnmatch
import importlib
import importlib.util
import os

from . import report


class ComparatorError(Exception):
    pass


_REGISTRY = {}


def register(name):
    """Class decorator registering a comparator under ``name``."""
    def deco(cls):
        if not (isinstance(cls, type) and issubclass(cls, Comparator)):
            raise TypeError("register() expects a Comparator subclass")
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return deco


def unregister(name):
    _REGISTRY.pop(name, None)


def names():
    return sorted(_REGISTRY)


def get(name, options=None):
    if name not in _REGISTRY:
        raise ComparatorError("unknown comparator '%s' (known: %s)"
                              % (name, ", ".join(names())))
    return _REGISTRY[name](options or {})


def load_plugin(spec):
    """Import a plug-in given a module name or a path to a ``.py`` file.
    Importing it is enough: plug-ins call :func:`register` at import time."""
    if spec.endswith(".py") or os.sep in spec:
        if not os.path.isfile(spec):
            raise ComparatorError("plugin file not found: %s" % spec)
        mod_name = "difftool_plugin_" + os.path.splitext(os.path.basename(spec))[0]
        s = importlib.util.spec_from_file_location(mod_name, spec)
        mod = importlib.util.module_from_spec(s)
        s.loader.exec_module(mod)
        return mod
    try:
        return importlib.import_module(spec)
    except ImportError as e:
        raise ComparatorError("cannot import plugin %s: %s" % (spec, e))


class Comparator(object):
    """Base class.

    Options common to all comparators (in the scenario ``comparators``
    entry): ``include`` / ``exclude`` are lists of fnmatch patterns matched
    against the message type (e.g. ``"*KeyValuePair"``); only selected
    messages are passed to :meth:`compare_windows`.
    """
    name = "base"

    def __init__(self, options=None):
        self.options = dict(options or {})
        self.include = self.options.get("include")
        self.exclude = self.options.get("exclude", [])

    def selects(self, type_name):
        if self.include and not any(fnmatch.fnmatch(type_name, p) for p in self.include):
            return False
        return not any(fnmatch.fnmatch(type_name, p) for p in self.exclude)

    def select(self, windows):
        """Filter windows by type selection, keeping window indices."""
        return [[m for m in w if self.selects(m.type)] for w in windows]

    def compare(self, ada_windows, cpp_windows):
        diffs = self.compare_windows(self.select(ada_windows), self.select(cpp_windows))
        for d in diffs:
            d.comparator = self.name
        return diffs

    def compare_windows(self, ada_windows, cpp_windows):
        raise NotImplementedError


def _flatten(windows):
    return [m for w in windows for m in w]


@register("canonical")
class CanonicalComparator(Comparator):
    """Strict comparison of canonical windows, window by window.

    Within a window messages are matched as multisets (order already
    canonical).  Differences are reported as missing / extra messages, and
    same-type leftovers are paired up to report field-level mismatches.
    """

    def compare_windows(self, ada_windows, cpp_windows):
        diffs = []
        for wi in range(max(len(ada_windows), len(cpp_windows))):
            a = ada_windows[wi] if wi < len(ada_windows) else []
            c = cpp_windows[wi] if wi < len(cpp_windows) else []
            diffs.extend(self.compare_window(wi, a, c))
        return diffs

    def compare_window(self, wi, a, c):
        diffs = []
        remaining_c = list(c)
        left_a = []
        for m in a:
            for j, o in enumerate(remaining_c):
                if o == m:
                    del remaining_c[j]
                    break
            else:
                left_a.append(m)
        # pair leftovers of same type for a field-level view
        for m in left_a:
            partner = next((o for o in remaining_c if o.type == m.type), None)
            if partner is not None:
                remaining_c.remove(partner)
                for path, x, y in report.diff_values(m.as_dict(), partner.as_dict()):
                    diffs.append(report.Difference(
                        report.MISMATCH, "%s differs" % m.type, wi, m.type,
                        ada=x, cpp=y, path=path))
            else:
                diffs.append(report.Difference(
                    report.MISSING_IN_CPP, "%s produced by Ada only" % m.type,
                    wi, m.type, ada=m.as_dict()))
        for o in remaining_c:
            diffs.append(report.Difference(
                report.EXTRA_IN_CPP, "%s produced by C++ only" % o.type,
                wi, o.type, cpp=o.as_dict()))
        return diffs


@register("count")
class CountComparator(Comparator):
    """Compare only how many messages of each type were produced
    (ignores window structure and contents)."""

    def compare_windows(self, ada_windows, cpp_windows):
        def counts(ws):
            r = {}
            for m in _flatten(ws):
                r[m.type] = r.get(m.type, 0) + 1
            return r
        ca, cc = counts(ada_windows), counts(cpp_windows)
        diffs = []
        for t in sorted(set(ca) | set(cc)):
            if ca.get(t, 0) != cc.get(t, 0):
                diffs.append(report.Difference(
                    report.COUNT, "%s count differs" % t, None, t,
                    ada=ca.get(t, 0), cpp=cc.get(t, 0), path="count"))
        return diffs


@register("types")
class TypeSetComparator(Comparator):
    """Compare only the *set* of message types produced."""

    def compare_windows(self, ada_windows, cpp_windows):
        ta = {m.type for m in _flatten(ada_windows)}
        tc = {m.type for m in _flatten(cpp_windows)}
        diffs = [report.Difference(report.MISSING_IN_CPP, "type %s only from Ada" % t,
                                   None, t, ada=t) for t in sorted(ta - tc)]
        diffs += [report.Difference(report.EXTRA_IN_CPP, "type %s only from C++" % t,
                                    None, t, cpp=t) for t in sorted(tc - ta)]
        return diffs


@register("superset")
class SupersetComparator(Comparator):
    """Every Ada message must appear in C++ output (anywhere); extra C++
    messages are tolerated.  Useful while a port is incomplete."""

    def compare_windows(self, ada_windows, cpp_windows):
        pool = _flatten(cpp_windows)
        diffs = []
        for wi, w in enumerate(ada_windows):
            for m in w:
                if m in pool:
                    pool.remove(m)
                else:
                    diffs.append(report.Difference(
                        report.MISSING_IN_CPP, "%s produced by Ada only" % m.type,
                        wi, m.type, ada=m.as_dict()))
        return diffs


@register("field_subset")
class FieldSubsetComparator(Comparator):
    """Like ``canonical`` but only the body fields listed in option
    ``fields`` (list of top-level names) are compared."""

    def compare_windows(self, ada_windows, cpp_windows):
        fields = set(self.options.get("fields", []))
        if not fields:
            raise ComparatorError("field_subset requires a non-empty 'fields' option")

        def proj(ws):
            out = []
            for w in ws:
                nw = []
                for m in w:
                    n = type(m)(m.type, {}, {k: v for k, v in m.body.items() if k in fields}, m.t_ms)
                    nw.append(n)
                out.append(nw)
            return out
        return CanonicalComparator({}).compare_windows(proj(ada_windows), proj(cpp_windows))


def run_all(specs, ada_windows, cpp_windows):
    """Run every comparator spec (``{"name":..., ...options}``) and
    concatenate the differences."""
    diffs = []
    for spec in specs:
        opts = {k: v for k, v in spec.items() if k != "name"}
        diffs.extend(get(spec["name"], opts).compare(ada_windows, cpp_windows))
    return diffs
