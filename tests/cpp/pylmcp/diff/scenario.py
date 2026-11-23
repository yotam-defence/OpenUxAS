"""Scenario file format (JSON) parsing and validation.

A scenario fully describes one differential run: which services are enabled,
the LMCP messages to replay, timing/settle parameters, how outputs are
normalised and which comparators are used.  The format is documented in
README.md.  Parsing is strict: unknown keys and wrong types are rejected with
a path-qualified error so scenario typos do not silently weaken the parity
gate.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import SCENARIO_FORMAT_VERSION, SIDES


class ScenarioError(ValueError):
    """Invalid scenario or recording file."""


# ---------------------------------------------------------------- helpers

def _check_keys(obj: Any, path: str, allowed: set,
                required: Optional[set] = None) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise ScenarioError("%s: expected an object" % path)
    unknown = set(obj) - allowed
    if unknown:
        raise ScenarioError("%s: unknown key(s) %s (allowed: %s)" % (
            path, sorted(unknown), sorted(allowed)))
    missing = (required or set()) - set(obj)
    if missing:
        raise ScenarioError("%s: missing key(s) %s" % (path, sorted(missing)))
    return obj


def _int(obj: Dict[str, Any], key: str, path: str, default: int,
         minimum: int = 0) -> int:
    v = obj.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ScenarioError("%s.%s: expected integer >= %d" %
                            (path, key, minimum))
    return v


def _str_list(v: Any, path: str) -> List[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ScenarioError("%s: expected a list of strings" % path)
    return list(v)


def _attr_str(v: Any, path: str) -> str:
    """Convert a JSON scalar to an XML attribute value."""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float, str)):
        return str(v)
    raise ScenarioError("%s: attribute values must be string/number/bool"
                        % path)


# ------------------------------------------------------------------ model

@dataclass
class XmlNode:
    """A generic XML element (used for services and nested children)."""
    tag: str
    attributes: Dict[str, str] = field(default_factory=dict)
    children: List["XmlNode"] = field(default_factory=list)


@dataclass
class ServiceSpec:
    type: str
    attributes: Dict[str, str] = field(default_factory=dict)
    children: List[XmlNode] = field(default_factory=list)
    sides: List[str] = field(default_factory=lambda: list(SIDES))


@dataclass
class ReplayStep:
    """One message to inject.

    Exactly one of ``frame_hex`` (a complete raw ZeroMQ frame, as captured by
    ``run-diff record``) or ``lmcp`` (type + fields, packed with pylmcp) is
    set.
    """
    label: str = ""
    delay_ms: int = 0
    settle_ms: Optional[int] = None
    frame_hex: Optional[str] = None
    lmcp: Optional[Dict[str, Any]] = None


@dataclass
class Timing:
    startup_ms: int = 2000
    settle_ms: int = 300
    drain_ms: int = 500
    shutdown_ms: int = 3000


@dataclass
class CaptureOptions:
    echo_filter: str = "bytes"       # bytes | envelope | none
    window: str = "step"             # step | all | fixed:<ms>
    min_messages: int = 0
    exclude_types: List[str] = field(default_factory=list)


@dataclass
class NormaliseOptions:
    strip_fields: Optional[List[str]] = None   # None -> canonical defaults
    id_fields: Optional[List[str]] = None
    id_mode: str = "strip"                     # strip | remap
    float_digits: int = 6
    keep_service_id: bool = False
    keep_source_entity: bool = True


@dataclass
class ComparatorRule:
    match: List[str]
    use: str = "exact"
    options: Dict[str, Any] = field(default_factory=dict)
    service: str = ""


@dataclass
class Scenario:
    name: str
    description: str = ""
    entity_id: int = 100
    entity_type: str = "Aircraft"
    pub_url: str = "tcp://127.0.0.1:5560"
    pull_url: str = "tcp://127.0.0.1:5561"
    services: List[ServiceSpec] = field(default_factory=list)
    timing: Timing = field(default_factory=Timing)
    steps: List[ReplayStep] = field(default_factory=list)
    capture: CaptureOptions = field(default_factory=CaptureOptions)
    normalise: NormaliseOptions = field(default_factory=NormaliseOptions)
    comparators: List[ComparatorRule] = field(default_factory=list)
    source_path: Optional[str] = None
    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def services_for(self, side: str) -> List[ServiceSpec]:
        return [s for s in self.services if side in s.sides]

    def capture_fingerprint(self, side: str) -> str:
        """Hash of everything that influences the *raw* capture of a side.

        Normalisation/comparator settings are excluded on purpose so golden
        files stay valid when only the comparison is tuned.
        """
        data = {
            "name": self.name,
            "entity": [self.entity_id, self.entity_type],
            "bus": [self.pub_url, self.pull_url],
            "services": [[s.type, s.attributes,
                          [_node_dict(c) for c in s.children]]
                         for s in self.services_for(side)],
            "timing": vars(self.timing),
            "steps": [vars(s) for s in self.steps],
            "capture": [self.capture.echo_filter, self.capture.window,
                        self.capture.exclude_types],
        }
        blob = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


def _node_dict(n: XmlNode) -> Dict[str, Any]:
    return {"tag": n.tag, "attributes": n.attributes,
            "children": [_node_dict(c) for c in n.children]}


# ---------------------------------------------------------------- parsing

def _parse_node(obj: Any, path: str) -> XmlNode:
    _check_keys(obj, path, {"tag", "attributes", "children"}, {"tag"})
    attrs = {k: _attr_str(v, "%s.attributes.%s" % (path, k))
             for k, v in obj.get("attributes", {}).items()}
    kids = [_parse_node(c, "%s.children[%d]" % (path, i))
            for i, c in enumerate(obj.get("children", []))]
    return XmlNode(obj["tag"], attrs, kids)


def _parse_service(obj: Any, path: str) -> ServiceSpec:
    _check_keys(obj, path, {"type", "attributes", "children", "sides"},
                {"type"})
    if not isinstance(obj["type"], str) or not obj["type"]:
        raise ScenarioError("%s.type: expected non-empty string" % path)
    sides = _str_list(obj.get("sides", list(SIDES)), path + ".sides")
    bad = [s for s in sides if s not in SIDES]
    if bad or not sides:
        raise ScenarioError("%s.sides: must be a non-empty subset of %s"
                            % (path, list(SIDES)))
    attrs = obj.get("attributes", {})
    if not isinstance(attrs, dict):
        raise ScenarioError("%s.attributes: expected an object" % path)
    return ServiceSpec(
        type=obj["type"],
        attributes={k: _attr_str(v, "%s.attributes.%s" % (path, k))
                    for k, v in attrs.items()},
        children=[_parse_node(c, "%s.children[%d]" % (path, i))
                  for i, c in enumerate(obj.get("children", []))],
        sides=sides)


def _parse_step(obj: Any, path: str) -> ReplayStep:
    _check_keys(obj, path, {"label", "delay_ms", "settle_ms", "frame_hex",
                            "lmcp", "recording"})
    present = [k for k in ("frame_hex", "lmcp", "recording") if k in obj]
    if len(present) != 1:
        raise ScenarioError("%s: exactly one of frame_hex/lmcp/recording "
                            "is required" % path)
    step = ReplayStep(label=str(obj.get("label", "")),
                      delay_ms=_int(obj, "delay_ms", path, 0))
    if "settle_ms" in obj:
        step.settle_ms = _int(obj, "settle_ms", path, 0)
    if "frame_hex" in obj:
        try:
            bytes.fromhex(obj["frame_hex"])
        except (ValueError, TypeError):
            raise ScenarioError("%s.frame_hex: not a hex string" % path)
        step.frame_hex = obj["frame_hex"]
    elif "lmcp" in obj:
        _check_keys(obj["lmcp"], path + ".lmcp",
                    {"type", "fields", "source_entity_id",
                     "source_service_id", "source_group"}, {"type"})
        step.lmcp = obj["lmcp"]
    return step


def load_recording(path: str) -> List[ReplayStep]:
    """Load a JSON-lines recording (see ``run-diff record``).

    Each line: ``{"delay_ms": int, "frame_hex": "...", "label": "..."}``.
    Blank lines and lines starting with ``#`` are ignored.
    """
    steps = []
    with open(path, "r", encoding="utf-8") as fd:
        for n, line in enumerate(fd, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except ValueError as e:
                raise ScenarioError("%s:%d: %s" % (path, n, e))
            _check_keys(obj, "%s:%d" % (path, n),
                        {"delay_ms", "frame_hex", "label", "settle_ms"},
                        {"frame_hex"})
            steps.append(_parse_step(obj, "%s:%d" % (path, n)))
    return steps


def parse_scenario(data: Any, base_dir: str = ".",
                   source_path: Optional[str] = None) -> Scenario:
    """Build a Scenario from decoded JSON ``data``."""
    allowed = {"format_version", "name", "description", "entity", "bus",
               "services", "timing", "replay", "capture", "normalise",
               "comparators"}
    _check_keys(data, "scenario", allowed, {"format_version", "name"})
    if data["format_version"] != SCENARIO_FORMAT_VERSION:
        raise ScenarioError("scenario.format_version: unsupported (%r, "
                            "expected %d)" % (data["format_version"],
                                              SCENARIO_FORMAT_VERSION))
    name = data["name"]
    if not isinstance(name, str) or not name or \
            any(c in name for c in "/\\ "):
        raise ScenarioError("scenario.name: non-empty string without "
                            "slashes/spaces required")
    sc = Scenario(name=name, description=str(data.get("description", "")),
                  source_path=source_path, _raw=data)

    if "entity" in data:
        e = _check_keys(data["entity"], "entity", {"id", "type"})
        sc.entity_id = _int(e, "id", "entity", 100)
        sc.entity_type = str(e.get("type", "Aircraft"))
    if "bus" in data:
        b = _check_keys(data["bus"], "bus", {"pub", "pull"})
        sc.pub_url = str(b.get("pub", sc.pub_url))
        sc.pull_url = str(b.get("pull", sc.pull_url))

    svcs = data.get("services", [])
    if not isinstance(svcs, list):
        raise ScenarioError("services: expected a list")
    sc.services = [_parse_service(s, "services[%d]" % i)
                   for i, s in enumerate(svcs)]

    if "timing" in data:
        t = _check_keys(data["timing"], "timing", set(vars(Timing())))
        sc.timing = Timing(**{k: _int(t, k, "timing", getattr(Timing(), k))
                              for k in vars(Timing())})

    steps: List[ReplayStep] = []
    replay = data.get("replay", [])
    if not isinstance(replay, list):
        raise ScenarioError("replay: expected a list")
    for i, r in enumerate(replay):
        if isinstance(r, dict) and "recording" in r:
            _check_keys(r, "replay[%d]" % i, {"recording"})
            rec = r["recording"]
            if not isinstance(rec, str):
                raise ScenarioError("replay[%d].recording: string" % i)
            rec_path = rec if os.path.isabs(rec) else \
                os.path.join(base_dir, rec)
            try:
                steps.extend(load_recording(rec_path))
            except OSError as e:
                raise ScenarioError("replay[%d]: cannot read recording: %s"
                                    % (i, e))
        else:
            steps.append(_parse_step(r, "replay[%d]" % i))
    sc.steps = steps

    if "capture" in data:
        c = _check_keys(data["capture"], "capture",
                        {"echo_filter", "window", "min_messages",
                         "exclude_types"})
        sc.capture = CaptureOptions(
            echo_filter=c.get("echo_filter", "bytes"),
            window=c.get("window", "step"),
            min_messages=_int(c, "min_messages", "capture", 0),
            exclude_types=_str_list(c.get("exclude_types", []),
                                    "capture.exclude_types"))
        if sc.capture.echo_filter not in ("bytes", "envelope", "none"):
            raise ScenarioError("capture.echo_filter: bytes|envelope|none")
        w = sc.capture.window
        if w not in ("step", "all"):
            if not (w.startswith("fixed:") and w[6:].isdigit()
                    and int(w[6:]) > 0):
                raise ScenarioError("capture.window: step|all|fixed:<ms>")

    if "normalise" in data:
        n = _check_keys(data["normalise"], "normalise",
                        {"strip_fields", "id_fields", "id_mode",
                         "float_digits", "keep_service_id",
                         "keep_source_entity"})
        sc.normalise = NormaliseOptions(
            strip_fields=None if "strip_fields" not in n else
            _str_list(n["strip_fields"], "normalise.strip_fields"),
            id_fields=None if "id_fields" not in n else
            _str_list(n["id_fields"], "normalise.id_fields"),
            id_mode=n.get("id_mode", "strip"),
            float_digits=_int(n, "float_digits", "normalise", 6),
            keep_service_id=bool(n.get("keep_service_id", False)),
            keep_source_entity=bool(n.get("keep_source_entity", True)))
        if sc.normalise.id_mode not in ("strip", "remap"):
            raise ScenarioError("normalise.id_mode: strip|remap")

    rules = data.get("comparators", [])
    if not isinstance(rules, list):
        raise ScenarioError("comparators: expected a list")
    for i, r in enumerate(rules):
        p = "comparators[%d]" % i
        _check_keys(r, p, {"match", "use", "options", "service"}, {"match"})
        match = r["match"]
        match = [match] if isinstance(match, str) else \
            _str_list(match, p + ".match")
        opts = r.get("options", {})
        if not isinstance(opts, dict):
            raise ScenarioError("%s.options: expected an object" % p)
        sc.comparators.append(ComparatorRule(
            match=match, use=str(r.get("use", "exact")), options=opts,
            service=str(r.get("service", ""))))
    return sc


def load_scenario(path: str) -> Scenario:
    """Load and validate a scenario JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as fd:
            data = json.load(fd)
    except OSError as e:
        raise ScenarioError("cannot read %s: %s" % (path, e))
    except ValueError as e:
        raise ScenarioError("%s: invalid JSON: %s" % (path, e))
    return parse_scenario(data, os.path.dirname(os.path.abspath(path)),
                          source_path=os.path.abspath(path))
