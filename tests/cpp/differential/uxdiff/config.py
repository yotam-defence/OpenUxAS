"""XML configuration generation (stdlib only).

Both binaries consume the same UxAS XML schema; the only difference is that
the Ada binary finds the C++ message hub through the PublishPull bridge
addresses, so it is given the same <Bridge> element as the hub that hosts it.
"""

from xml.etree.ElementTree import Element, SubElement, tostring

ALL_MESSAGES = "abcdefghijklmnopqrstuvwxyz" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _subst(value, ctx):
    if isinstance(value, str):
        for k, v in ctx.items():
            value = value.replace("{%s}" % k, str(v))
    return value


def _build(parent, spec, ctx):
    if isinstance(spec, str):
        spec = {"Type": spec}
    tag = spec.get("tag", "Service")
    attrs = {k: _subst(v, ctx) for k, v in spec.get("attrs", {}).items()}
    if "Type" in spec:
        attrs["Type"] = _subst(spec["Type"], ctx)
    el = SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if spec.get("text") is not None:
        el.text = _subst(spec["text"], ctx)
    for child in spec.get("children", []):
        _build(el, dict(child, tag=child.get("tag", "Subscribe")), ctx)
    return el


def bridge_element(parent, pub, pull, subscriptions):
    el = SubElement(parent, "Bridge", {
        "Type": "LmcpObjectNetworkPublishPullBridge",
        "AddressPUB": pub, "AddressPULL": pull})
    for s in (subscriptions or list(ALL_MESSAGES)):
        SubElement(el, "SubscribeToMessage", {"MessageType": s})
    return el


def make_config(scenario, side, pub, pull, workdir, include_services=True,
                include_bridge=True):
    """Return the XML (bytes) for ``side`` ('cpp'|'ada') of ``scenario``."""
    ctx = {"PUB": pub, "PULL": pull, "WORKDIR": workdir,
           "ENTITY_ID": scenario.entity_id,
           "ENTITY_TYPE": scenario.entity_type}
    root = Element("UxAS", {"FormatVersion": "1.0",
                            "EntityID": str(scenario.entity_id),
                            "EntityType": scenario.entity_type})
    for k, v in scenario.root_attrs.items():
        root.set(k, str(_subst(v, ctx)))
    if include_bridge:
        bridge_element(root, pub, pull, scenario.subscriptions)
    if include_services:
        for spec in scenario.services["common"] + scenario.services[side]:
            _build(root, spec, ctx)
    return (b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n' +
            tostring(root, encoding="utf-8"))
