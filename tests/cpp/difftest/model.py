"""Plain data classes shared by the harness (no third-party imports)."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DelayStep:
    delay_ms: int


@dataclass
class SendStep:
    """Send one LMCP object.

    ``spec`` is the JSON object description (see scenario.build_object).
    """
    spec: Dict[str, Any]
    source_entity_id: Optional[int] = None
    source_service_id: int = 0
    source_group: str = ""


@dataclass
class WindowStep:
    """Close a capture window after ``duration_ms``.

    Every message observed since the previous window closed (including during
    the delays/sends preceding this step) belongs to this window.
    """
    name: str
    duration_ms: int = 500
    ordered: bool = False           # keep arrival order instead of sorting
    types: Optional[List[str]] = None  # restrict comparison to these types
    min_messages: Optional[int] = None  # sanity bound, on both sides
    max_messages: Optional[int] = None


@dataclass
class ServiceSpec:
    type_ada: str
    type_cpp: str
    attributes: Dict[str, str] = field(default_factory=dict)
    children: List[Dict[str, Any]] = field(default_factory=list)
    impls: Optional[List[str]] = None  # None = both


@dataclass
class ConfigSpec:
    entity_id: int = 100
    entity_type: str = "Aircraft"
    services: List[ServiceSpec] = field(default_factory=list)
    # Message types the bridge subscribes to (default: every letter prefix,
    # as pylmcp.uxas.PublishPullBridge does).
    bridge_subscriptions: Optional[List[str]] = None


@dataclass
class Scenario:
    name: str
    description: str = ""
    path: Optional[str] = None
    startup_settle_ms: int = 1500
    shutdown_settle_ms: int = 200
    capture_startup: bool = False
    config: ConfigSpec = field(default_factory=ConfigSpec)
    normalise: Dict[str, Any] = field(default_factory=dict)
    comparators: Dict[str, Any] = field(default_factory=dict)
    services: Dict[str, str] = field(default_factory=dict)  # service id->name
    steps: List[Any] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def windows(self) -> List[WindowStep]:
        return [s for s in self.steps if isinstance(s, WindowStep)]
