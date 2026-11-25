"""Scenario loading and validation.

A scenario is a JSON (or YAML, if PyYAML is installed) document.  See
README.md for the full schema.
"""
import base64
import binascii
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

IMPLS = ("cpp", "ada")

DEFAULT_PUB = "tcp://127.0.0.1:5560"
DEFAULT_PULL = "tcp://127.0.0.1:5561"


class ScenarioError(Exception):
    """Raised for malformed scenarios."""


@dataclass
class ReplayStep:
    delay_ms: int
    type: Optional[str] = None
    fields: Dict[str, Any] = field(default_factory=dict)
    raw_b64: Optional[str] = None
    address: Optional[str] = None
    source_entity_id: Optional[int] = None
    source_service_id: Optional[int] = None
    source_group: str = ""

    @property
    def raw(self) -> Optional[bytes]:
        return None if self.raw_b64 is None else base64.b64decode(self.raw_b64)


@dataclass
class Capture:
    subscribe: List[str]
    quiet_ms: int = 1000
    max_wait_ms: int = 10000
    ignore_types: List[str] = field(default_factory=list)


@dataclass
class ComparatorSpec:
    name: str = "canonical"
    options: Dict[str, Any] = field(default_factory=dict)
    by_type: Dict[str, "ComparatorSpec"] = field(default_factory=dict)


@dataclass
class Scenario:
    name: str
    description: str
    entity_id: int
    entity_type: str
    services: List[Dict[str, Any]]
    pub_address: str
    pull_address: str
    capture: Capture
    replay: List[ReplayStep]
    comparator: ComparatorSpec
    path: Optional[str] = None
    run_duration_s: Optional[float] = None


def _load_text(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fd:
        text = fd.read()
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise ScenarioError(
                "PyYAML is required to read %s; install it (pip install "
                "pyyaml) or convert the scenario to JSON" % path)
        data = yaml.safe_load(text)
    else:
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ScenarioError("invalid JSON in %s: %s" % (path, e))
    if not isinstance(data, dict):
        raise ScenarioError("%s: top level must be an object" % path)
    return data


def _parse_comparator(raw: Any, where: str) -> ComparatorSpec:
    if raw is None:
        return ComparatorSpec()
    if isinstance(raw, str):
        return ComparatorSpec(name=raw)
    if not isinstance(raw, dict):
        raise ScenarioError("%s: comparator must be a string or object"
                            % where)
    unknown = set(raw) - {"name", "options", "by_type"}
    if unknown:
        raise ScenarioError("%s: unknown comparator keys %s"
                            % (where, sorted(unknown)))
    by_type = {}
    for t, sub in (raw.get("by_type") or {}).items():
        by_type[t] = _parse_comparator(sub, where + ".by_type." + t)
        if by_type[t].by_type:
            raise ScenarioError("%s: by_type cannot be nested" % where)
    return ComparatorSpec(name=raw.get("name", "canonical"),
                          options=dict(raw.get("options") or {}),
                          by_type=by_type)


def _parse_step(raw: Any, idx: int) -> ReplayStep:
    where = "replay[%d]" % idx
    if not isinstance(raw, dict):
        raise ScenarioError("%s must be an object" % where)
    unknown = set(raw) - {"delay_ms", "type", "fields", "raw_b64", "address",
                          "source_entity_id", "source_service_id",
                          "source_group"}
    if unknown:
        raise ScenarioError("%s: unknown keys %s" % (where, sorted(unknown)))
    delay = raw.get("delay_ms", 0)
    if not isinstance(delay, int) or isinstance(delay, bool) or delay < 0:
        raise ScenarioError("%s: delay_ms must be a non-negative integer"
                            % where)
    has_type = "type" in raw
    has_raw = "raw_b64" in raw
    if has_type == has_raw:
        raise ScenarioError(
            "%s: exactly one of 'type' (+'fields') or 'raw_b64' required"
            % where)
    if has_raw:
        if "fields" in raw:
            raise ScenarioError("%s: 'fields' not allowed with raw_b64"
                                % where)
        try:
            base64.b64decode(raw["raw_b64"], validate=True)
        except (binascii.Error, ValueError, TypeError):
            raise ScenarioError("%s: raw_b64 is not valid base64" % where)
        if not raw.get("address"):
            raise ScenarioError("%s: raw_b64 requires 'address'" % where)
    fields = raw.get("fields") or {}
    if not isinstance(fields, dict):
        raise ScenarioError("%s: fields must be an object" % where)
    return ReplayStep(delay_ms=delay, type=raw.get("type"), fields=fields,
                      raw_b64=raw.get("raw_b64"), address=raw.get("address"),
                      source_entity_id=raw.get("source_entity_id"),
                      source_service_id=raw.get("source_service_id"),
                      source_group=raw.get("source_group", ""))


def parse_scenario(data: Dict[str, Any], path: Optional[str] = None
                   ) -> Scenario:
    allowed = {"name", "description", "entity_id", "entity_type", "services",
               "bridge", "capture", "replay", "comparator", "run_duration_s"}
    unknown = set(data) - allowed
    if unknown:
        raise ScenarioError("unknown top-level keys %s" % sorted(unknown))
    if "name" not in data:
        raise ScenarioError("'name' is required")
    services = data.get("services", [])
    if not isinstance(services, list):
        raise ScenarioError("'services' must be a list")
    for i, s in enumerate(services):
        if not isinstance(s, dict) or "Type" not in s:
            raise ScenarioError("services[%d] must be an object with 'Type'"
                                % i)
        impl = s.get("impl")
        if impl is not None:
            if isinstance(impl, str):
                impl = [impl]
            if not set(impl) <= set(IMPLS):
                raise ScenarioError("services[%d]: impl must be within %s"
                                    % (i, IMPLS))
    bridge = data.get("bridge") or {}
    cap = data.get("capture")
    if not isinstance(cap, dict) or not cap.get("subscribe"):
        raise ScenarioError("'capture.subscribe' (list of message types or "
                            "['*']) is required")
    capture = Capture(subscribe=list(cap["subscribe"]),
                      quiet_ms=int(cap.get("quiet_ms", 1000)),
                      max_wait_ms=int(cap.get("max_wait_ms", 10000)),
                      ignore_types=list(cap.get("ignore_types", [])))
    replay_raw = data.get("replay", [])
    if not isinstance(replay_raw, list):
        raise ScenarioError("'replay' must be a list")
    replay = [_parse_step(r, i) for i, r in enumerate(replay_raw)]
    return Scenario(
        name=str(data["name"]),
        description=str(data.get("description", "")),
        entity_id=int(data.get("entity_id", 100)),
        entity_type=str(data.get("entity_type", "Aircraft")),
        services=services,
        pub_address=bridge.get("pub", DEFAULT_PUB),
        pull_address=bridge.get("pull", DEFAULT_PULL),
        capture=capture,
        replay=replay,
        comparator=_parse_comparator(data.get("comparator"), "comparator"),
        path=path,
        run_duration_s=data.get("run_duration_s"))


def load_scenario(path: str) -> Scenario:
    if not os.path.isfile(path):
        raise ScenarioError("scenario not found: %s" % path)
    return parse_scenario(_load_text(path), path)
