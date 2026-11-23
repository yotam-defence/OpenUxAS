"""Scenario loading, validation and (de)serialisation of replay messages."""

import base64
import binascii
import copy
import hashlib
import json
import os

from . import lmcp

DEFAULT_TIMING = {
    "startup_settle_ms": 1500,   # after launching a process, before replay
    "post_replay_settle_ms": 1500,  # after last replay step, before stop
    "timeout_s": 60,             # hard wall clock limit per side
    "shutdown_grace_s": 5,       # SIGINT -> SIGTERM -> SIGKILL spacing
}

SIDES = ("cpp", "ada")


class ScenarioError(ValueError):
    pass


class ReplayStep(object):
    def __init__(self, index, delay_ms, envelope, label=""):
        self.index = index
        self.delay_ms = delay_ms
        self.envelope = envelope
        self.label = label


def _decode_frame(entry, where):
    if "frame_hex" in entry:
        try:
            return bytes.fromhex(entry["frame_hex"])
        except ValueError as exc:
            raise ScenarioError("%s: bad frame_hex: %s" % (where, exc))
    if "frame_b64" in entry:
        try:
            return base64.b64decode(entry["frame_b64"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ScenarioError("%s: bad frame_b64: %s" % (where, exc))
    raise ScenarioError("%s: needs frame_hex or frame_b64" % where)


class Scenario(object):
    def __init__(self, data, path=None):
        self.data = data
        self.path = path
        self.name = data["name"]
        self.description = data.get("description", "")
        ent = data.get("entity", {})
        self.entity_id = int(ent.get("id", 100))
        self.entity_type = str(ent.get("type", "Aircraft"))
        self.timing = dict(DEFAULT_TIMING)
        self.timing.update(data.get("timing", {}))
        self.capture = dict(data.get("capture", {}))
        self.subscriptions = list(self.capture.get("subscriptions", []))
        self.comparator = data.get("comparator", "default")
        self.comparator_options = dict(data.get("comparator_options", {}))
        self.normalise_options = dict(data.get("normalise", {}))
        self.normalise_options.setdefault("window", self.capture.get("window", "all"))
        self.exclude_echo = bool(self.capture.get("exclude_echo", False))
        self.plugins = list(data.get("plugins", []))
        self.binaries = copy.deepcopy(data.get("binaries", {}))
        self.root_attrs = dict(data.get("root_attrs", {}))
        self.services = self._services(data.get("services", []))
        self.replay = self._replay(data.get("replay", []))

    @staticmethod
    def _services(svc):
        if isinstance(svc, list):
            svc = {"common": svc}
        if not isinstance(svc, dict):
            raise ScenarioError("services must be a list or an object")
        out = {"common": [], "cpp": [], "ada": []}
        for k, v in svc.items():
            if k not in out:
                raise ScenarioError("services key %r not in common/cpp/ada" % k)
            if not isinstance(v, list):
                raise ScenarioError("services.%s must be a list" % k)
            out[k] = v
        return out

    @staticmethod
    def _replay(entries):
        steps = []
        for i, e in enumerate(entries):
            where = "replay[%d]" % i
            frame = _decode_frame(e, where)
            try:
                header = lmcp.parse_frame(frame)
            except lmcp.LmcpError as exc:
                raise ScenarioError("%s: %s" % (where, exc))
            delay = e.get("delay_ms", 0)
            if not isinstance(delay, (int, float)) or delay < 0:
                raise ScenarioError("%s: delay_ms must be >= 0" % where)
            address = e.get("address")
            if not address:
                raise ScenarioError("%s: address required (e.g. %s)" %
                                    (where, lmcp.KEY_VALUE_PAIR_ADDRESS))
            env = lmcp.Envelope(
                address=address, payload=frame,
                content_type=e.get("content_type", "lmcp"),
                descriptor=e.get("descriptor", address),
                source_group=e.get("source_group", ""),
                source_entity_id=e.get("source_entity_id", 0),
                source_service_id=e.get("source_service_id", 0))
            steps.append(ReplayStep(i, delay, env, e.get("label", header.series)))
        return steps

    def digest(self):
        """Hash of everything that influences the *output* (for goldens)."""
        keep = {k: self.data.get(k) for k in
                ("entity", "services", "replay", "capture", "root_attrs",
                 "normalise")}
        text = json.dumps(keep, sort_keys=True)
        return hashlib.sha256(text.encode()).hexdigest()


def validate(data):
    if not isinstance(data, dict):
        raise ScenarioError("scenario must be a JSON object")
    if not data.get("name"):
        raise ScenarioError("scenario needs a 'name'")
    unknown = set(data) - {
        "name", "description", "entity", "services", "replay", "capture",
        "comparator", "comparator_options", "normalise", "timing", "plugins",
        "binaries", "root_attrs", "$schema", "comment"}
    if unknown:
        raise ScenarioError("unknown scenario keys: %s" % sorted(unknown))
    for k in data.get("timing", {}):
        if k not in DEFAULT_TIMING:
            raise ScenarioError("unknown timing key %r" % k)
    return data


def load_scenario(path):
    try:
        with open(path, "r", encoding="utf-8") as fd:
            data = json.load(fd)
    except (OSError, ValueError) as exc:
        raise ScenarioError("cannot read scenario %s: %s" % (path, exc))
    return Scenario(validate(data), path=os.path.abspath(path))


def scenario_from_dict(data):
    return Scenario(validate(data))
