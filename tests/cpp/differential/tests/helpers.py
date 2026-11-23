"""Shared helpers for the fixture-free tests."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from uxdiff import lmcp, scenario as scn  # noqa: E402


def kvp_env(key, value, service_id=0, entity_id=100):
    return lmcp.Envelope(lmcp.KEY_VALUE_PAIR_ADDRESS,
                         lmcp.key_value_pair_frame(key, value),
                         source_entity_id=entity_id,
                         source_service_id=service_id)


def kvp_raw(key, value, **kw):
    return kvp_env(key, value, **kw).pack()


def make_scenario(steps=3, **over):
    data = {
        "name": "unit",
        "timing": {"startup_settle_ms": 0, "post_replay_settle_ms": 10},
        "capture": {"subscriptions": ["afrl.cmasi.KeyValuePair"]},
        "comparator": "heartbeat",
        "replay": [{"delay_ms": 5, "address": lmcp.KEY_VALUE_PAIR_ADDRESS,
                    "frame_hex": lmcp.key_value_pair_frame(
                        "heartbeat", str(i)).hex()} for i in range(steps)],
    }
    data.update(over)
    return scn.scenario_from_dict(data)


class raises(object):
    """Minimal pytest.raises replacement so tests run without pytest."""

    def __init__(self, exc):
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            raise AssertionError("did not raise %s" % self.exc.__name__)
        return issubclass(et, self.exc)
