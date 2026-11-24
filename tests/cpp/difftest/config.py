"""Generate equivalent UxAS XML configurations for Ada and C++."""
from xml.etree.ElementTree import Element, SubElement, tostring

from difftest.scenario import Scenario


def _add_children(parent, children):
    for ch in children:
        el = SubElement(parent, ch["tag"],
                        {k: str(v) for k, v in ch.get("attributes", {}).items()})
        _add_children(el, ch.get("children", []))


def build_config(sc: Scenario, impl: str, pub=None, pull=None) -> bytes:
    """Return the XML config for ``impl`` ('ada' or 'cpp').

    Both implementations get the same entity, the same PublishPull bridge
    (the capture/injection point of the harness) and the same services,
    except services restricted with ``only``.
    """
    assert impl in ("ada", "cpp")
    root = Element("UxAS", {"FormatVersion": "1.0",
                            "EntityID": str(sc.entity_id),
                            "EntityType": sc.entity_type})
    bridge = SubElement(root, "Bridge", {
        "Type": "LmcpObjectNetworkPublishPullBridge",
        "AddressPUB": pub or sc.pub,
        "AddressPULL": pull or sc.pull})
    for c in sc.subscribe:
        SubElement(bridge, "SubscribeToMessage", {"MessageType": c})
    for s in sc.services:
        if s.only not in (None, impl):
            continue
        el = SubElement(root, s.kind, {"Type": s.type, **s.attributes})
        _add_children(el, s.children)
    return (b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
            + tostring(root, encoding="utf-8").replace(b"><", b">\n<"))
