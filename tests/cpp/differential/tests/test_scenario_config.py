from helpers import *  # noqa
import json
import os
import tempfile
from xml.etree import ElementTree as ET
from uxdiff import config, scenario as scn, lmcp

HERE = os.path.dirname(os.path.abspath(__file__))
HEARTBEAT = os.path.join(HERE, "..", "scenarios", "heartbeat.json")


def test_shipped_heartbeat_scenario_loads():
    sc = scn.load_scenario(HEARTBEAT)
    assert sc.name == "heartbeat" and len(sc.replay) == 5
    assert sc.comparator == "heartbeat"
    assert all(s.envelope.address == lmcp.KEY_VALUE_PAIR_ADDRESS
               for s in sc.replay)
    assert all(lmcp.parse_frame(s.envelope.payload).checksum_ok
               for s in sc.replay)


def test_base64_frames_and_validation_errors():
    fr = lmcp.key_value_pair_frame("a", "b")
    import base64
    sc = scn.scenario_from_dict({"name": "x", "replay": [
        {"address": "a.b", "frame_b64": base64.b64encode(fr).decode()}]})
    assert sc.replay[0].envelope.payload == fr
    bad = [
        {"name": "x", "bogus": 1},
        {"replay": []},
        {"name": "x", "replay": [{"address": "a"}]},
        {"name": "x", "replay": [{"address": "a", "frame_hex": "zz"}]},
        {"name": "x", "replay": [{"frame_hex": fr.hex()}]},
        {"name": "x", "replay": [{"address": "a", "frame_hex": "00" * 30}]},
        {"name": "x", "timing": {"nope": 1}},
        {"name": "x", "services": {"java": []}},
    ]
    for d in bad:
        with raises(scn.ScenarioError):
            scn.scenario_from_dict(d)


def test_load_scenario_bad_file():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        with open(p, "w") as fd:
            fd.write("{not json")
        with raises(scn.ScenarioError):
            scn.load_scenario(p)
    with raises(scn.ScenarioError):
        scn.load_scenario("/nonexistent/s.json")


def test_digest_changes_with_replay_not_comparator():
    a = make_scenario(2)
    assert a.digest() == make_scenario(2, comparator="default").digest()
    assert a.digest() != make_scenario(3).digest()


def test_xml_cfg_equivalent_for_both_sides():
    sc = make_scenario(1, services={
        "common": [{"Type": "AutomationRequestValidatorService",
                    "attrs": {"WorkDir": "{WORKDIR}"}}],
        "ada": ["AdaOnly"], "cpp": ["CppOnly"]},
        entity={"id": 42, "type": "Vehicle"})
    pub, pull = "tcp://127.0.0.1:1", "tcp://127.0.0.1:2"
    cpp = ET.fromstring(config.make_config(sc, "cpp", pub, pull, "/w"))
    ada = ET.fromstring(config.make_config(sc, "ada", pub, pull, "/w"))
    for root in (cpp, ada):
        assert root.get("EntityID") == "42" and root.get("EntityType") == "Vehicle"
        b = root.find("Bridge")
        assert b.get("AddressPUB") == pub and b.get("AddressPULL") == pull
        assert [s.get("MessageType") for s in b] == ["afrl.cmasi.KeyValuePair"]
        assert root.find("Service").get("WorkDir") == "/w"
    assert [s.get("Type") for s in cpp.findall("Service")][-1] == "CppOnly"
    assert [s.get("Type") for s in ada.findall("Service")][-1] == "AdaOnly"
    hub = ET.fromstring(config.make_config(sc, "ada", pub, pull, "/w",
                                           include_services=False))
    assert hub.find("Service") is None and hub.find("Bridge") is not None


def test_xml_default_subscribes_to_everything_and_declaration():
    sc = make_scenario(1, capture={})
    xml = config.make_config(sc, "cpp", "p", "q", "/w")
    assert xml.startswith(b'<?xml version="1.0"') and xml.count(b"<?xml") == 1
    assert len(ET.fromstring(xml).find("Bridge")) == 52


def test_replay_source_entity_defaults_to_scenario_entity():
    sc = make_scenario(1, entity={"id": 7})
    assert sc.replay[0].envelope.source_entity_id == 7
    d = make_scenario(1, entity={"id": 7})
    d.data["replay"][0]["source_entity_id"] = 3
    assert scn.scenario_from_dict(d.data).replay[0].envelope.source_entity_id == 3
