"""Turn scenario replay steps into raw ZeroMQ frames."""
from __future__ import annotations

from typing import Any

from .scenario import ReplayStep


def _build_value(v: Any):
    """Recursively turn ``{"@type": ..., fields}`` dicts into LMCP Objects."""
    from pylmcp import Object
    if isinstance(v, dict) and "@type" in v:
        kw = {k: _build_value(x) for k, x in v.items() if k != "@type"}
        return Object(v["@type"], **kw)
    if isinstance(v, list):
        return [_build_value(x) for x in v]
    return v


def build_frame(step: ReplayStep, default_entity: int = 100) -> bytes:
    """Return the raw frame for a step (pylmcp only needed for ``lmcp``)."""
    if step.frame_hex is not None:
        return bytes.fromhex(step.frame_hex)
    from pylmcp import Object
    from pylmcp.message import Message
    spec = step.lmcp
    fields = {k: _build_value(v) for k, v in spec.get("fields", {}).items()}
    obj = Object(spec["type"], **fields)
    return Message(obj,
                   source_entity_id=spec.get("source_entity_id",
                                             default_entity),
                   source_service_id=spec.get("source_service_id", 0),
                   source_group=spec.get("source_group", "")).pack()
