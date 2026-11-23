"""Scenario format.

A scenario is a JSON (or YAML, when PyYAML is installed) document::

    {
      "name": "smoke_heartbeat",
      "description": "...",
      "entity_id": 100,
      "startup_settle_ms": 1500,        # wait after launching a binary
      "config": {                       # XML config template per binary,
        "ada": "smoke_heartbeat/config.xml",   # relative to the scenario file
        "cpp": "smoke_heartbeat/config.xml"
      },
      "messages": [                     # ordered replay list
        {"type": "afrl.cmasi.KeyValuePair",
         "fields": {"Key": "heartbeat", "Value": "1"},
         "delay_ms": 200,               # settle delay *after* sending
         "source_entity_id": 100, "source_service_id": 0}
      ],
      "capture": {
        "window_ms": 1500,              # keep capturing this long after the last send
        "include_descriptors": [],      # empty = everything
        "exclude_descriptors": []
      },
      "canonical": {                    # see difftest.canon.CanonConfig
        "strip_fields": ["Time"],
        "remap_fields": [],
        "float_digits": 6,
        "sort_window_ms": null
      },
      "comparators": {                  # descriptor (fnmatch glob) -> comparator
        "afrl.cmasi.KeyValuePair": "exact",
        "*": {"name": "numeric", "abs": 1e-6}
      },
      "plugins": []                     # python modules registering comparators
    }

Config templates are plain text with ``${NAME}`` placeholders (see
``TEMPLATE_VARS``).  The runner substitutes them per binary run.
"""
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

BINARIES = ("ada", "cpp")

#: placeholders available in XML config templates
TEMPLATE_VARS = ("ENTITY_ID", "PUB_ADDRESS", "PULL_ADDRESS", "RUN_DIR")


class ScenarioError(Exception):
    pass


@dataclass
class ReplayMessage:
    type: str
    fields: Dict[str, Any] = field(default_factory=dict)
    delay_ms: int = 100
    source_entity_id: int = 100
    source_service_id: int = 0


@dataclass
class CaptureSpec:
    window_ms: int = 1000
    include_descriptors: List[str] = field(default_factory=list)
    exclude_descriptors: List[str] = field(default_factory=list)


@dataclass
class Scenario:
    name: str
    description: str = ""
    entity_id: int = 100
    startup_settle_ms: int = 1500
    config: Dict[str, str] = field(default_factory=dict)
    messages: List[ReplayMessage] = field(default_factory=list)
    capture: CaptureSpec = field(default_factory=CaptureSpec)
    canonical: Dict[str, Any] = field(default_factory=dict)
    comparators: Dict[str, Any] = field(default_factory=dict)
    plugins: List[str] = field(default_factory=list)
    path: Optional[str] = None  # file the scenario was loaded from

    @property
    def base_dir(self) -> str:
        return os.path.dirname(os.path.abspath(self.path)) if self.path else "."

    def config_template(self, binary: str) -> str:
        """Return the XML template text for ``binary`` ('ada' or 'cpp')."""
        rel = self.config.get(binary)
        if rel is None:
            raise ScenarioError("scenario %s has no config for %s" %
                                (self.name, binary))
        full = rel if os.path.isabs(rel) else os.path.join(self.base_dir, rel)
        try:
            with open(full, "r", encoding="utf-8") as fd:
                return fd.read()
        except OSError as e:
            raise ScenarioError("cannot read config template %s: %s" %
                                (full, e))


def render_template(text: str, **values: Any) -> str:
    """Substitute ``${NAME}`` placeholders; unknown placeholders are errors."""
    def sub(m):
        name = m.group(1)
        if name not in values:
            raise ScenarioError("unknown template variable ${%s}" % name)
        return str(values[name])
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", sub, text)


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ScenarioError(msg)


def from_dict(data: Dict[str, Any], path: Optional[str] = None) -> Scenario:
    _require(isinstance(data, dict), "scenario must be a mapping")
    _require("name" in data and isinstance(data["name"], str) and data["name"],
             "scenario requires a non-empty 'name'")
    unknown = set(data) - {"name", "description", "entity_id",
                           "startup_settle_ms", "config", "messages",
                           "capture", "canonical", "comparators", "plugins"}
    _require(not unknown, "unknown scenario keys: %s" % sorted(unknown))

    config = data.get("config", {})
    _require(isinstance(config, dict) and
             set(config) <= set(BINARIES),
             "'config' must map %s to template paths" % (BINARIES,))

    entity_id = int(data.get("entity_id", 100))
    msgs = []
    raw_msgs = data.get("messages", [])
    _require(isinstance(raw_msgs, list), "'messages' must be a list")
    for i, m in enumerate(raw_msgs):
        _require(isinstance(m, dict) and isinstance(m.get("type"), str),
                 "messages[%d] requires a 'type'" % i)
        bad = set(m) - {"type", "fields", "delay_ms", "source_entity_id",
                        "source_service_id"}
        _require(not bad, "messages[%d]: unknown keys %s" % (i, sorted(bad)))
        delay = int(m.get("delay_ms", 100))
        _require(delay >= 0, "messages[%d]: delay_ms must be >= 0" % i)
        msgs.append(ReplayMessage(
            type=m["type"],
            fields=dict(m.get("fields", {})),
            delay_ms=delay,
            source_entity_id=int(m.get("source_entity_id", entity_id)),
            source_service_id=int(m.get("source_service_id", 0))))

    cap = data.get("capture", {})
    _require(isinstance(cap, dict), "'capture' must be a mapping")
    capture = CaptureSpec(
        window_ms=int(cap.get("window_ms", 1000)),
        include_descriptors=list(cap.get("include_descriptors", [])),
        exclude_descriptors=list(cap.get("exclude_descriptors", [])))
    _require(capture.window_ms >= 0, "capture.window_ms must be >= 0")

    return Scenario(
        name=data["name"],
        description=data.get("description", ""),
        entity_id=entity_id,
        startup_settle_ms=int(data.get("startup_settle_ms", 1500)),
        config=dict(config),
        messages=msgs,
        capture=capture,
        canonical=dict(data.get("canonical", {})),
        comparators=dict(data.get("comparators", {})),
        plugins=list(data.get("plugins", [])),
        path=path)


def load(path: str) -> Scenario:
    """Load a scenario file (.json, or .yaml/.yml when PyYAML is available)."""
    try:
        with open(path, "r", encoding="utf-8") as fd:
            text = fd.read()
    except OSError as e:
        raise ScenarioError("cannot read scenario %s: %s" % (path, e))
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise ScenarioError("PyYAML is required to load %s" % path)
        data = yaml.safe_load(text)
    else:
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ScenarioError("invalid JSON in %s: %s" % (path, e))
    return from_dict(data, path=path)
