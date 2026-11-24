"""Scenario format (JSON) and loader.

Example::

    {
      "name": "smoke_heartbeat",
      "entity_id": 100,
      "entity_type": "Aircraft",
      "bridge": {"pub": "tcp://127.0.0.1:5560", "pull": "tcp://127.0.0.1:5561"},
      "services": [{"type": "SomeService", "attributes": {"A": "1"},
                    "children": [{"tag": "X", "attributes": {"B": "2"}}],
                    "only": "ada"}],
      "settle": {"startup_s": 2.0, "between_messages_s": 0.2, "final_s": 1.0},
      "messages": [
        {"label": "hb1", "lmcp": {"type": "KeyValuePair",
                                   "fields": {"Key": "hb", "Value": "1"}}},
        {"label": "raw", "hex": "<hex of full wire message>", "delay_s": 0.5}
      ],
      "normalise": {"id_mode": "renumber"},
      "comparators": [{"name": "canonical", "match": ["*"]}],
      "plugins": []
    }
"""
import copy
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ALL_MESSAGES = ("abcdefghijklmnopqrstuvwxyz" "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
IMPLS = ("ada", "cpp")


class ScenarioError(ValueError):
    pass


@dataclass
class ServiceSpec:
    type: str
    attributes: Dict[str, str] = field(default_factory=dict)
    children: List[Dict[str, Any]] = field(default_factory=list)
    only: Optional[str] = None  # None | "ada" | "cpp"
    kind: str = "Service"  # XML tag: Service or Bridge


@dataclass
class MessageSpec:
    label: str
    hex: Optional[str] = None  # full wire message (address$attrs$payload)
    lmcp: Optional[Dict[str, Any]] = None
    delay_s: Optional[float] = None  # settle delay AFTER sending
    source_entity_id: Optional[int] = None
    source_service_id: int = 0


@dataclass
class Scenario:
    name: str
    description: str = ""
    entity_id: int = 100
    entity_type: str = "Aircraft"
    pub: str = "tcp://127.0.0.1:5560"
    pull: str = "tcp://127.0.0.1:5561"
    subscribe: List[str] = field(default_factory=lambda: list(ALL_MESSAGES))
    services: List[ServiceSpec] = field(default_factory=list)
    startup_s: float = 2.0
    between_messages_s: float = 0.2
    final_s: float = 1.0
    messages: List[MessageSpec] = field(default_factory=list)
    normalise: Dict[str, Any] = field(default_factory=dict)
    comparators: List[Dict[str, Any]] = field(default_factory=list)
    plugins: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    path: Optional[str] = None

    def fingerprint(self) -> str:
        """Hash of everything that can influence the outputs (not the
        normalisation / comparators, which are applied after capture)."""
        relevant = {k: self.raw.get(k) for k in
                    ("entity_id", "entity_type", "bridge", "services",
                     "settle", "messages", "subscribe")}
        blob = json.dumps(relevant, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


def _req(cond, msg):
    if not cond:
        raise ScenarioError(msg)


def parse_scenario(data: Dict[str, Any], path: Optional[str] = None) -> Scenario:
    _req(isinstance(data, dict), "scenario must be a JSON object")
    _req(isinstance(data.get("name"), str) and data["name"],
         "scenario requires a non-empty string 'name'")
    unknown = set(data) - {"name", "description", "entity_id", "entity_type",
                           "bridge", "subscribe", "services", "settle",
                           "messages", "normalise", "comparators", "plugins"}
    _req(not unknown, "unknown scenario keys: %s" % sorted(unknown))

    sc = Scenario(name=data["name"], raw=copy.deepcopy(data), path=path)
    sc.description = data.get("description", "")
    sc.entity_id = int(data.get("entity_id", sc.entity_id))
    sc.entity_type = str(data.get("entity_type", sc.entity_type))

    bridge = data.get("bridge", {})
    sc.pub = bridge.get("pub", sc.pub)
    sc.pull = bridge.get("pull", sc.pull)
    if "subscribe" in data:
        _req(isinstance(data["subscribe"], list), "'subscribe' must be a list")
        sc.subscribe = [str(s) for s in data["subscribe"]]

    for i, s in enumerate(data.get("services", [])):
        _req(isinstance(s, dict) and "type" in s,
             "services[%d] requires 'type'" % i)
        only = s.get("only")
        _req(only in (None,) + IMPLS,
             "services[%d].only must be one of %s" % (i, IMPLS))
        kind = s.get("kind", "Service")
        _req(kind in ("Service", "Bridge"),
             "services[%d].kind must be Service or Bridge" % i)
        sc.services.append(ServiceSpec(
            type=s["type"],
            attributes={k: str(v) for k, v in s.get("attributes", {}).items()},
            children=s.get("children", []), only=only, kind=kind))

    settle = data.get("settle", {})
    sc.startup_s = float(settle.get("startup_s", sc.startup_s))
    sc.between_messages_s = float(
        settle.get("between_messages_s", sc.between_messages_s))
    sc.final_s = float(settle.get("final_s", sc.final_s))
    for k in ("startup_s", "between_messages_s", "final_s"):
        _req(getattr(sc, k) >= 0, "settle.%s must be >= 0" % k)

    msgs = data.get("messages", [])
    _req(isinstance(msgs, list), "'messages' must be a list")
    for i, m in enumerate(msgs):
        _req(isinstance(m, dict), "messages[%d] must be an object" % i)
        has_hex, has_lmcp = "hex" in m, "lmcp" in m
        _req(has_hex != has_lmcp,
             "messages[%d] needs exactly one of 'hex' or 'lmcp'" % i)
        if has_hex:
            try:
                bytes.fromhex(m["hex"])
            except (ValueError, TypeError):
                raise ScenarioError("messages[%d].hex is not valid hex" % i)
        else:
            _req(isinstance(m["lmcp"], dict) and "type" in m["lmcp"],
                 "messages[%d].lmcp requires 'type'" % i)
        delay = m.get("delay_s")
        _req(delay is None or float(delay) >= 0,
             "messages[%d].delay_s must be >= 0" % i)
        sc.messages.append(MessageSpec(
            label=m.get("label", "msg%d" % i),
            hex=m.get("hex"), lmcp=m.get("lmcp"),
            delay_s=None if delay is None else float(delay),
            source_entity_id=m.get("source_entity_id"),
            source_service_id=int(m.get("source_service_id", 0))))

    sc.normalise = data.get("normalise", {})
    sc.comparators = data.get("comparators", [])
    _req(isinstance(sc.comparators, list), "'comparators' must be a list")
    for i, c in enumerate(sc.comparators):
        _req(isinstance(c, dict) and "name" in c,
             "comparators[%d] requires 'name'" % i)
    sc.plugins = list(data.get("plugins", []))
    return sc


def load_scenario(path: str) -> Scenario:
    try:
        with open(path, "r", encoding="utf-8") as fd:
            data = json.load(fd)
    except json.JSONDecodeError as e:
        raise ScenarioError("%s: invalid JSON: %s" % (path, e))
    except OSError as e:
        raise ScenarioError("cannot read scenario %s: %s" % (path, e))
    return parse_scenario(data, path=os.path.abspath(path))
