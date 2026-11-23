"""Live runner: start a UxAS binary, replay a scenario over ZeroMQ, capture.

Requires ``pyzmq`` and ``pylmcp`` (imported lazily so the rest of the
package works without them).  Both binaries are driven identically:

  * the XML config template is rendered into a private run directory;
  * the binary is launched as ``<bin> -cfgPath <cfg>`` with that directory as
    its cwd (so work directories/logs do not collide);
  * a SUB socket connects to the bridge PUB address and captures *everything*
    (the scenario's capture filters are applied afterwards);
  * replay messages are PUSHed to the bridge PULL address in order, sleeping
    ``delay_ms`` after each;
  * capturing continues for ``capture.window_ms`` after the last message;
  * the process gets SIGINT, then SIGKILL after a grace period.
"""
import os
import shlex
import signal
import subprocess
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional

from difftest.scenario import Scenario, render_template

DEFAULT_PUB = "tcp://127.0.0.1:5560"
DEFAULT_PULL = "tcp://127.0.0.1:5561"


class RunnerError(Exception):
    pass


def find_binary(binary: str, explicit: Optional[str] = None) -> Optional[str]:
    """Locate the executable for 'ada' or 'cpp' (None if not found)."""
    import shutil
    env = {"ada": "UXAS_ADA_BIN", "cpp": "UXAS_CPP_BIN"}[binary]
    candidates = [explicit, os.environ.get(env)]
    if binary == "cpp":
        candidates += ["obj/cpp/uxas"]
    else:
        candidates += ["obj/ada/uxas-ada"]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return os.path.abspath(c)
    names = ["uxas"] if binary == "cpp" else ["uxas-ada", "uxas_ada"]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _build_message(spec, Message, Object):
    def conv(v):
        if isinstance(v, dict) and "_type" in v:
            return Object(v["_type"],
                          **{k: conv(x) for k, x in v.items() if k != "_type"})
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v
    obj = Object(spec.type, **{k: conv(v) for k, v in spec.fields.items()})
    return Message(obj=obj, source_entity_id=spec.source_entity_id,
                   source_service_id=spec.source_service_id)


def _decode(raw: bytes, t_ms: float, Message) -> Optional[Dict[str, Any]]:
    try:
        m = Message.unpack(raw)
    except Exception as e:  # undecodable: keep a marker so it shows in diffs
        return {"t_ms": t_ms, "descriptor": "<undecodable>",
                "content_type": "raw", "source_entity_id": None,
                "source_service_id": None,
                "obj": {"error": str(e), "head": raw[:64].hex()}}
    return {"t_ms": t_ms, "address": m.address, "descriptor": m.descriptor,
            "content_type": m.content_type, "source_group": m.source_group,
            "source_entity_id": m.source_entity_id,
            "source_service_id": m.source_service_id,
            "obj": m.obj.as_dict()}


def run_binary(scenario: Scenario, binary: str, exe: str,
               extra_args: Optional[List[str]] = None,
               pub: str = DEFAULT_PUB, pull: str = DEFAULT_PULL,
               keep_dir: Optional[str] = None,
               log: Callable[[str], None] = lambda s: None
               ) -> List[Dict[str, Any]]:
    """Run one binary against the scenario and return the raw capture."""
    try:
        import zmq  # type: ignore
        from pylmcp import Object  # type: ignore
        from pylmcp.message import Message  # type: ignore
    except ImportError as e:
        raise RunnerError("live runs need pyzmq and pylmcp deps: %s" % e)

    tmp = keep_dir or tempfile.mkdtemp(prefix="difftest-%s-%s-" %
                                       (scenario.name, binary))
    os.makedirs(tmp, exist_ok=True)
    cfg_path = os.path.join(tmp, "cfg.xml")
    with open(cfg_path, "w", encoding="utf-8") as fd:
        fd.write(render_template(
            scenario.config_template(binary),
            ENTITY_ID=scenario.entity_id, PUB_ADDRESS=pub,
            PULL_ADDRESS=pull, RUN_DIR=tmp))

    cmd = [exe, "-cfgPath", cfg_path] + list(extra_args or [])
    log("launching %s: %s" % (binary, " ".join(shlex.quote(c) for c in cmd)))
    out = open(os.path.join(tmp, "stdout.log"), "wb")
    proc = subprocess.Popen(cmd, cwd=tmp, stdout=out, stderr=subprocess.STDOUT)

    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    push = ctx.socket(zmq.PUSH)
    captured: List[Dict[str, Any]] = []
    try:
        sub.setsockopt(zmq.SUBSCRIBE, b"")
        sub.connect(pub)
        push.connect(pull)
        poller = zmq.Poller()
        poller.register(sub, zmq.POLLIN)
        t0 = time.monotonic()

        def drain(duration_s: float):
            end = time.monotonic() + duration_s
            while True:
                left = end - time.monotonic()
                if left <= 0:
                    break
                if proc.poll() is not None:
                    raise RunnerError("%s exited early with code %s "
                                      "(see %s/stdout.log)" %
                                      (binary, proc.returncode, tmp))
                if poller.poll(timeout=min(left, 0.05) * 1000):
                    raw = sub.recv()
                    t_ms = (time.monotonic() - t0) * 1000.0
                    d = _decode(raw, t_ms, Message)
                    if d:
                        captured.append(d)

        drain(scenario.startup_settle_ms / 1000.0)
        for spec in scenario.messages:
            push.send(_build_message(spec, Message, Object).pack())
            drain(spec.delay_ms / 1000.0)
        drain(scenario.capture.window_ms / 1000.0)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        out.close()
        sub.close(0)
        push.close(0)
        ctx.term()
    return captured
