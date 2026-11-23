"""Generate equivalent UxAS XML configurations for both implementations.

Both ``uxas`` (C++) and ``uxas_ada`` are started with the same shape of
file: the enabled services of the scenario plus a
``LmcpObjectNetworkPublishPullBridge``.  The only difference is who owns the
sockets: the C++ ``uxas`` binds the bridge addresses itself, while
``uxas_ada`` connects to them (see ``Get_LMCP_Socket_Addresses`` in
src/ada/src/main/uxas_ada.adb), so the harness binds them for the Ada side
(``bus.HubBus``).  The XML therefore is identical modulo the services
filtered by ``sides``.
"""
from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement, tostring, indent

from .scenario import Scenario, XmlNode

# Same set of message address prefixes pylmcp.uxas.PublishPullBridge uses.
ALL_MESSAGES = "abcdefghijklmnopqrstuvwxyz" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _node(parent: Element, n: XmlNode) -> None:
    el = SubElement(parent, n.tag, attrib=dict(n.attributes))
    for c in n.children:
        _node(el, c)


def build_config(scenario: Scenario, side: str) -> bytes:
    """Return the XML configuration for ``side`` ('ada' or 'cpp')."""
    root = Element("UxAS", attrib={
        "FormatVersion": "1.0",
        "EntityID": str(scenario.entity_id),
        "EntityType": scenario.entity_type})
    for svc in scenario.services_for(side):
        el = SubElement(root, "Service",
                        attrib=dict(type_first(svc.type, svc.attributes)))
        for c in svc.children:
            _node(el, c)
    bridge = SubElement(root, "Bridge", attrib={
        "Type": "LmcpObjectNetworkPublishPullBridge",
        "AddressPUB": scenario.pub_url,
        "AddressPULL": scenario.pull_url})
    for c in ALL_MESSAGES:
        SubElement(bridge, "SubscribeToMessage", attrib={"MessageType": c})
    indent(root, space="    ")
    return (b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n' +
            tostring(root) + b"\n")


def type_first(type_name, attributes):
    """Attribute items with ``Type`` first (stable, readable output)."""
    items = [("Type", type_name)]
    items.extend((k, v) for k, v in attributes.items() if k != "Type")
    return items
