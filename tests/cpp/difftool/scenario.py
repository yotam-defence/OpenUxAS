"""Scenario file parsing (plain JSON)."""
import hashlib
import json
import os

from . import normalize


class ScenarioError(Exception):
    """Raised on a malformed scenario."""


DEFAULT_ENDPOINT = {"pub": "tcp://127.0.0.1:5560", "push": "tcp://127.0.0.1:5561"}


class Message(object):
    """One LMCP message to replay."""

    def __init__(self, cls, fields=None, delay_ms=0, source_entity_id=100,
                 source_service_id=0, source_group="", address=None):
        self.cls = cls
        self.fields = fields or {}
        self.delay_ms = delay_ms
        self.source_entity_id = source_entity_id
        self.source_service_id = source_service_id
        self.source_group = source_group
        self.address = address

    def as_dict(self):
        return {"class": self.cls, "fields": self.fields,
                "delay_ms": self.delay_ms,
                "source_entity_id": self.source_entity_id,
                "source_service_id": self.source_service_id,
                "source_group": self.source_group, "address": self.address}


class Scenario(object):
    """A parsed scenario.  See README.md for the format."""

    def __init__(self, name, ada_cfg, cpp_cfg, messages, ada_hub_cfg=None,
                 description="", startup_delay_ms=1000, settle_ms=1000,
                 capture=None, comparators=None, normalization=None,
                 endpoint=None, plugins=None, base_dir="."):
        self.name = name
        self.description = description
        self.ada_cfg = ada_cfg
        self.cpp_cfg = cpp_cfg
        self.ada_hub_cfg = ada_hub_cfg
        self.messages = messages
        self.startup_delay_ms = startup_delay_ms
        self.settle_ms = settle_ms
        self.capture = capture if capture is not None else [""]
        self.comparators = comparators or [{"name": "canonical"}]
        self.normalization = normalization or {}
        self.endpoint = dict(DEFAULT_ENDPOINT, **(endpoint or {}))
        self.plugins = plugins or []
        self.base_dir = base_dir

    def read_cfg(self, which):
        """Return the text of the XML config ``ada``, ``cpp`` or ``ada_hub``."""
        path = {"ada": self.ada_cfg, "cpp": self.cpp_cfg,
                "ada_hub": self.ada_hub_cfg}[which]
        if path is None:
            return None
        with open(path, "r") as fd:
            return fd.read()

    def normalization_options(self):
        return normalize.Options.from_dict(self.normalization)

    def reference_fingerprint(self):
        """Hash of everything that determines the Ada reference output.

        Used to detect stale golden files.  The C++ config is deliberately
        excluded: golden files only cache the Ada side.
        """
        h = hashlib.sha256()
        payload = {
            "ada_cfg": self.read_cfg("ada"),
            "ada_hub_cfg": self.read_cfg("ada_hub"),
            "messages": [m.as_dict() for m in self.messages],
            "capture": self.capture,
            "endpoint": self.endpoint,
            "startup_delay_ms": self.startup_delay_ms,
            "settle_ms": self.settle_ms,
        }
        h.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
        return h.hexdigest()


def _need(d, key, typ, where):
    if key not in d:
        raise ScenarioError("%s: missing required key '%s'" % (where, key))
    if not isinstance(d[key], typ):
        raise ScenarioError("%s: key '%s' must be %s" % (where, key, typ.__name__))
    return d[key]


def _nonneg(d, key, default, where):
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        raise ScenarioError("%s: '%s' must be a non-negative number" % (where, key))
    return v


def parse_message(d, idx):
    where = "messages[%d]" % idx
    if not isinstance(d, dict):
        raise ScenarioError("%s must be an object" % where)
    cls = _need(d, "class", str, where)
    fields = d.get("fields", {})
    if not isinstance(fields, dict):
        raise ScenarioError("%s: 'fields' must be an object" % where)
    return Message(
        cls=cls, fields=fields,
        delay_ms=_nonneg(d, "delay_ms", 0, where),
        source_entity_id=d.get("source_entity_id", 100),
        source_service_id=d.get("source_service_id", 0),
        source_group=d.get("source_group", ""),
        address=d.get("address"))


def parse(data, base_dir=".", check_files=True):
    """Build a :class:`Scenario` from a decoded JSON object."""
    if not isinstance(data, dict):
        raise ScenarioError("scenario must be a JSON object")
    where = "scenario"
    name = _need(data, "name", str, where)
    unknown = set(data) - {
        "name", "description", "ada_cfg", "cpp_cfg", "ada_hub_cfg", "messages",
        "startup_delay_ms", "settle_ms", "capture", "comparators",
        "normalization", "endpoint", "plugins", "$comment"}
    if unknown:
        raise ScenarioError("unknown scenario keys: %s" % ", ".join(sorted(unknown)))

    def path(key, required=True):
        if key not in data:
            if required:
                raise ScenarioError("scenario: missing required key '%s'" % key)
            return None
        p = _need(data, key, str, where)
        p = p if os.path.isabs(p) else os.path.join(base_dir, p)
        if check_files and not os.path.isfile(p):
            raise ScenarioError("%s: file not found: %s" % (key, p))
        return p

    msgs = _need(data, "messages", list, where)
    messages = [parse_message(m, i) for i, m in enumerate(msgs)]

    capture = data.get("capture", [""])
    if not isinstance(capture, list) or not all(isinstance(c, str) for c in capture):
        raise ScenarioError("scenario: 'capture' must be a list of strings")

    comparators = data.get("comparators", [{"name": "canonical"}])
    if not isinstance(comparators, list) or not comparators:
        raise ScenarioError("scenario: 'comparators' must be a non-empty list")
    norm_comps = []
    for i, c in enumerate(comparators):
        if isinstance(c, str):
            c = {"name": c}
        if not isinstance(c, dict) or not isinstance(c.get("name"), str):
            raise ScenarioError("comparators[%d] needs a string 'name'" % i)
        norm_comps.append(c)

    norm = data.get("normalization", {})
    if not isinstance(norm, dict):
        raise ScenarioError("scenario: 'normalization' must be an object")
    try:
        normalize.Options.from_dict(norm)
    except (ValueError, TypeError) as e:
        raise ScenarioError("normalization: %s" % e)

    plugins = data.get("plugins", [])
    if not isinstance(plugins, list):
        raise ScenarioError("scenario: 'plugins' must be a list")

    return Scenario(
        name=name, description=data.get("description", ""),
        ada_cfg=path("ada_cfg"), cpp_cfg=path("cpp_cfg"),
        ada_hub_cfg=path("ada_hub_cfg", required=False),
        messages=messages,
        startup_delay_ms=_nonneg(data, "startup_delay_ms", 1000, where),
        settle_ms=_nonneg(data, "settle_ms", 1000, where),
        capture=capture, comparators=norm_comps, normalization=norm,
        endpoint=data.get("endpoint"), plugins=plugins, base_dir=base_dir)


def load(filename):
    try:
        with open(filename, "r") as fd:
            data = json.load(fd)
    except (OSError, ValueError) as e:
        raise ScenarioError("cannot read scenario %s: %s" % (filename, e))
    return parse(data, base_dir=os.path.dirname(os.path.abspath(filename)))
