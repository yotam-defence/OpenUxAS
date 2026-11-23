#!/usr/bin/env python3
"""Regenerates heartbeat.json (frames are built with uxdiff.lmcp)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from uxdiff import lmcp  # noqa: E402

steps = []
for i in range(5):
    frame = lmcp.key_value_pair_frame("heartbeat", str(i))
    steps.append({"label": "heartbeat-%d" % i, "delay_ms": 200,
                  "address": lmcp.KEY_VALUE_PAIR_ADDRESS,
                  "frame_hex": frame.hex()})

scenario = {
    "name": "heartbeat",
    "description": "Smoke test: a KeyValuePair heartbeat sequence (no "
                   "AutomationRequest). Both binaries must publish the same "
                   "multiset of KeyValuePair messages.",
    "entity": {"id": 100, "type": "Aircraft"},
    "services": {"common": [], "cpp": [], "ada": []},
    "timing": {"startup_settle_ms": 1500, "post_replay_settle_ms": 1000,
               "timeout_s": 60, "shutdown_grace_s": 5},
    "capture": {"subscriptions": ["afrl.cmasi.KeyValuePair"],
                "window": "all", "exclude_echo": False},
    "comparator": "heartbeat",
    "comparator_options": {"keys": ["heartbeat"], "compare_values": True},
    "replay": steps,
}

with open(os.path.join(HERE, "heartbeat.json"), "w") as fd:
    json.dump(scenario, fd, indent=2)
    fd.write("\n")
