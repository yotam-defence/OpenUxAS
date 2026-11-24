import unittest

import _path  # noqa: F401
from uxas_diff import runner, scenario
from uxas_diff.capture import Transport, replay


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class MockTransport(Transport):
    """Echo transport driven by a fake clock (no zmq, no sleeping)."""

    def __init__(self, clock):
        self.clock = clock
        self.sent = []
        self.queue = []

    def send(self, data):
        self.sent.append(data)
        self.queue.append(data)

    def poll(self, timeout_ms):
        if self.queue:
            return self.queue.pop(0)
        self.clock.t += timeout_ms / 1000.0
        return None


class ReplayTest(unittest.TestCase):
    def test_phases_and_capture_window(self):
        clk = FakeClock()
        tr = MockTransport(clk)
        sc = {"startup_settle_ms": 300,
              "messages": [{"delay_ms": 100, "hex": "aa"},
                           {"delay_ms": 200},
                           {"delay_ms": 0, "hex": "bb"}],
              "capture": {"tail_ms": 150}}
        recs = replay(sc, tr, decode=lambda raw: {"descriptor": raw.hex(),
                                                  "obj": {}},
                      wire=lambda s: bytes.fromhex(s["hex"])
                      if "hex" in s else None, clock=clk)
        self.assertEqual(tr.sent, [b"\xaa", b"\xbb"])
        self.assertEqual([(r["descriptor"], r["phase"]) for r in recs],
                         [("aa", 1), ("bb", 3)])
        self.assertGreaterEqual(clk.t, 0.3 + 0.1 + 0.2 + 0.15 - 0.01)
        self.assertTrue(all("t_ms" in r for r in recs))


class ScenarioTest(unittest.TestCase):
    def test_smoke_loads(self):
        sc = scenario.load("smoke_heartbeat")
        self.assertEqual(sc["name"], "smoke_heartbeat")
        for which in ("ada", "cpp", "hub"):
            self.assertTrue(scenario.config_path(sc, which).endswith(".xml"))
        # no AutomationRequest / KeyValuePair in the heartbeat sequence
        text = str(sc["messages"])
        self.assertNotIn("AutomationRequest", text)
        self.assertNotIn("KeyValuePair", text)

    def test_validation(self):
        with self.assertRaises(scenario.ScenarioError):
            scenario.validate({"name": "x", "configs": {"cpp": "a"},
                               "messages": []})
        with self.assertRaises(scenario.ScenarioError):
            scenario.validate({"name": "x", "configs": {"cpp": "a", "ada": "b"},
                               "messages": [{"hex": "zz"}]})
        with self.assertRaises(scenario.ScenarioError):
            scenario.resolve("does_not_exist")


class RunnerHelpersTest(unittest.TestCase):
    def test_find_binary_missing(self):
        import os
        old = {k: os.environ.pop(k, None)
               for k in (runner.ENV_CPP, runner.ENV_ADA)}
        try:
            with self.assertRaises(runner.RunnerError):
                runner.find_binary("ada", "/nonexistent/uxas_ada")
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v

    def test_find_binary_env(self):
        import os
        import sys
        os.environ[runner.ENV_CPP] = sys.executable
        try:
            self.assertEqual(runner.find_binary("cpp", None), sys.executable)
        finally:
            del os.environ[runner.ENV_CPP]

    def test_render_config(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            s, t = os.path.join(d, "s"), os.path.join(d, "t")
            open(s, "w").write("a=${PUB_PORT} b=${PULL_PORT}")
            runner.render_config(s, t, 11, 22)
            self.assertEqual(open(t).read(), "a=11 b=22")
            open(s, "w").write("${BRIDGE_SUBSCRIPTIONS}")
            runner.render_config(s, t, 11, 22)
            subs = open(t).read().count("SubscribeToMessage")
            self.assertEqual(subs, 52)
            self.assertTrue(open(t).read().startswith(
                '<SubscribeToMessage MessageType="a" />'))
            self.assertTrue(open(t).read().endswith(
                '<SubscribeToMessage MessageType="Z" />'))


if __name__ == "__main__":
    unittest.main()
