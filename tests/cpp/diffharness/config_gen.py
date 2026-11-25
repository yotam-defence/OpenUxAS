"""Generate the UxAS XML configuration for each implementation.

The C++ ``uxas`` and the Ada ``uxas_ada`` consume the same XML dialect (see
examples/02d_Ada_WPM_WaterwaySearch/cfg_ada.xml vs cfg_cpp.xml), so a single
scenario description yields two files that differ only by per-element
``impl`` filters.
"""
from typing import Any, Dict
from xml.etree.ElementTree import Element, SubElement, tostring

from diffharness.scenario import IMPLS, Scenario

ALL_MESSAGES = ("abcdefghijklmnopqrstuvwxyz" "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _element(spec: Dict[str, Any], impl: str):
    only = spec.get("impl")
    if only is not None:
        if isinstance(only, str):
            only = [only]
        if impl not in only:
            return None
    tag = spec.get("tag", "Service")
    attrs = {k: _attr(v) for k, v in spec.items()
             if k not in ("tag", "impl", "children")}
    el = Element(tag, attrs)
    for child in spec.get("children", []):
        c = _element(child, impl)
        if c is not None:
            el.append(c)
    return el


def _attr(v: Any) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return str(v)


def build_config(scenario: Scenario, impl: str) -> bytes:
    """Return the XML configuration bytes for ``impl`` ('cpp' or 'ada')."""
    if impl not in IMPLS:
        raise ValueError("unknown implementation %r" % impl)
    attrs = {"FormatVersion": "1.0",
             "EntityID": str(scenario.entity_id),
             "EntityType": scenario.entity_type}
    if scenario.run_duration_s is not None:
        attrs["RunDuration_s"] = str(scenario.run_duration_s)
    root = Element("UxAS", attrs)
    for spec in scenario.services:
        el = _element(spec, impl)
        if el is not None:
            root.append(el)

    bridge = SubElement(root, "Bridge", {
        "Type": "LmcpObjectNetworkPublishPullBridge",
        "AddressPUB": scenario.pub_address,
        "AddressPULL": scenario.pull_address})
    subs = scenario.capture.subscribe
    if "*" in subs:
        subs = list(ALL_MESSAGES)
    for s in subs:
        SubElement(bridge, "SubscribeToMessage", {"MessageType": s})
    return (b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
            + tostring(root, encoding="utf-8") + b"\n")
