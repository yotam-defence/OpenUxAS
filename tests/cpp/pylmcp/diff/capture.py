"""Raw capture container and golden-file persistence.

Golden files store the *raw frames* (hex) with their window index, not the
canonical form, so normalisation/comparator settings can change without
re-running the Ada reference (Alire/GNAT is then not needed).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .messages import DecodedMessage, decode_frame

GOLDEN_VERSION = 1


class GoldenError(Exception):
    pass


@dataclass
class RawFrame:
    window: int
    t_ms: float
    data: bytes


@dataclass
class Capture:
    side: str
    scenario: str
    frames: List[RawFrame] = field(default_factory=list)
    fingerprint: str = ""
    source: str = "live"      # live | golden
    log_tail: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def decode(self, decoder=decode_frame) -> List[DecodedMessage]:
        return [decoder(f.data, window=f.window, t_ms=f.t_ms, side=self.side)
                for f in self.frames]

    def to_dict(self) -> Dict[str, Any]:
        return {"golden_version": GOLDEN_VERSION, "side": self.side,
                "meta": self.meta,
                "scenario": self.scenario, "fingerprint": self.fingerprint,
                "frames": [{"window": f.window, "t_ms": round(f.t_ms, 1),
                            "frame_hex": f.data.hex()}
                           for f in self.frames]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Capture":
        try:
            if d["golden_version"] != GOLDEN_VERSION:
                raise GoldenError("unsupported golden_version %r"
                                  % d["golden_version"])
            return cls(side=d["side"], scenario=d["scenario"],
                       fingerprint=d["fingerprint"], source="golden",
                       meta=dict(d.get("meta", {})),
                       frames=[RawFrame(f["window"], f.get("t_ms", 0.0),
                                        bytes.fromhex(f["frame_hex"]))
                               for f in d["frames"]])
        except (KeyError, TypeError, ValueError) as e:
            raise GoldenError("malformed golden file: %r" % (e,))


def golden_path(golden_dir: str, scenario: str, side: str) -> str:
    return os.path.join(golden_dir, "%s.%s.json" % (scenario, side))


def save_golden(golden_dir: str, capture: Capture) -> str:
    os.makedirs(golden_dir, exist_ok=True)
    path = golden_path(golden_dir, capture.scenario, capture.side)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fd:
        json.dump(capture.to_dict(), fd, indent=1, sort_keys=True)
        fd.write("\n")
    os.replace(tmp, path)
    return path


def load_golden(golden_dir: str, scenario: str, side: str,
                fingerprint: Optional[str] = None,
                allow_stale: bool = False) -> Capture:
    """Load a golden capture; raise GoldenError if missing/stale."""
    path = golden_path(golden_dir, scenario, side)
    try:
        with open(path, "r", encoding="utf-8") as fd:
            cap = Capture.from_dict(json.load(fd))
    except OSError:
        raise GoldenError("no golden file %s (record with --update-golden)"
                          % path)
    except ValueError as e:
        raise GoldenError("%s: invalid JSON: %s" % (path, e))
    if fingerprint and cap.fingerprint != fingerprint and not allow_stale:
        raise GoldenError(
            "golden %s is stale: scenario changed since it was recorded "
            "(re-record with --update-golden or pass --allow-stale-golden)"
            % path)
    return cap
