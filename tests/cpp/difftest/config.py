"""Render equivalent XML configurations for the Ada and C++ implementations.

Both implementations are driven from the same scenario ``config`` section and
the templates in ``configs/`` so the only differences are the ones declared
explicitly (e.g. a service whose type name differs between implementations).
"""
import os
import string
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring

from difftest import ADA, CPP
from difftest.model import Scenario

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "configs")
TEMPLATES = {ADA: "ada.xml.tmpl", CPP: "cpp.xml.tmpl"}

# Same default as pylmcp.uxas.ALL_MESSAGES
ALL_MESSAGES = ("abcdefghijklmnopqrstuvwxyz" "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _fragment(el: Element) -> str:
    return "    " + tostring(el, encoding="unicode")


def bridge_xml(scenario: Scenario, pub: str, pull: str) -> str:
    subs = scenario.config.bridge_subscriptions
    if subs is None:
        subs = list(ALL_MESSAGES)
    el = Element("Bridge", {"Type": "LmcpObjectNetworkPublishPullBridge",
                            "AddressPUB": pub, "AddressPULL": pull})
    for s in subs:
        SubElement(el, "SubscribeToMessage", {"MessageType": s})
    return _fragment(el)


def services_xml(scenario: Scenario, impl: str) -> str:
    out = []
    for svc in scenario.config.services:
        if svc.impls is not None and impl not in svc.impls:
            continue
        attrs = {"Type": svc.type_ada if impl == ADA else svc.type_cpp}
        attrs.update(svc.attributes)
        el = Element("Service", attrs)
        for ch in svc.children:
            SubElement(el, ch["tag"],
                       {k: str(v) for k, v in ch.get("attributes", {}).items()})
        out.append(_fragment(el))
    return "\n".join(out)


def render_config(impl: str, scenario: Scenario, pub: str, pull: str,
                  config_dir: Optional[str] = None) -> str:
    """Return the XML configuration text for ``impl``."""
    path = os.path.join(config_dir or CONFIG_DIR, TEMPLATES[impl])
    with open(path, encoding="utf-8") as fd:
        tmpl = string.Template(fd.read())
    return tmpl.substitute(
        ENTITY_ID=scenario.config.entity_id,
        ENTITY_TYPE=scenario.config.entity_type,
        BRIDGE=bridge_xml(scenario, pub, pull),
        SERVICES=services_xml(scenario, impl))
