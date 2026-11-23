import json
import os
import tempfile

SCEN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios")


def kv(t, value, req=None, service=3, key="heartbeat", entity=100, typ="afrl.cmasi.KeyValuePair"):
    obj = {"Key": key, "Value": value}
    if req is not None:
        obj["RequestID"] = req
    return {"t_ms": t, "address": typ, "descriptor": typ, "content_type": "lmcp",
            "source_group": "", "source_entity_id": entity, "source_service_id": service,
            "obj": obj}


class FakeProc(object):
    def __init__(self, name, argv):
        self.name, self.argv, self.stopped, self._alive = name, argv, False, True

    def alive(self):
        return self._alive

    def stop(self):
        self.stopped = True


class FakeLauncher(object):
    def __init__(self, die=()):
        self.procs, self.die = [], set(die)

    def __call__(self, argv, name):
        p = FakeProc(name, argv)
        if name in self.die:
            p._alive = False
        self.procs.append(p)
        return p


class FakeTransport(object):
    """Echoes every sent message back as a capture, like the bridge does."""
    instances = []

    def __init__(self, endpoint, capture):
        self.endpoint, self.capture, self.sent, self.closed = endpoint, capture, [], False
        self.t = 0
        FakeTransport.instances.append(self)

    def open(self):
        pass

    def send(self, msg):
        self.sent.append(msg)

    def captured(self):
        return [kv(10.0 * i, m.fields["Value"]) for i, m in enumerate(self.sent)]

    def close(self):
        self.closed = True


def write_scenario(directory, **over):
    for n in ("a.xml", "c.xml", "h.xml"):
        with open(os.path.join(directory, n), "w") as fd:
            fd.write("<UxAS/>")
    d = {"name": "t", "ada_cfg": "a.xml", "cpp_cfg": "c.xml",
         "messages": [{"class": "KeyValuePair", "delay_ms": 5,
                       "fields": {"Key": "k", "Value": "v1"}},
                      {"class": "KeyValuePair", "fields": {"Key": "k", "Value": "v2"}}],
         "settle_ms": 0, "startup_delay_ms": 0}
    d.update(over)
    path = os.path.join(directory, "s.json")
    with open(path, "w") as fd:
        json.dump(d, fd)
    return path


def tmpdir():
    return tempfile.TemporaryDirectory()
