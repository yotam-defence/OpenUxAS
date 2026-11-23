# Ada vs C++ differential replay harness

Parity gate for the Ada-to-C++ migration (milestones 1-7). It starts the Ada
reference `uxas_ada` and the C++ `uxas` with equivalent XML configs, replays a
recorded LMCP message sequence over ZeroMQ, captures the outbound LMCP
messages of each side, canonicalises them and diffs the result.

Pure Python 3 standard library. `pyzmq` is imported lazily and only for real
runs. `pylmcp` (needs `e3`) is imported lazily and only used to decode message
types that have no built-in decoder.

```
python3 run_differential.py scenarios/heartbeat.json \
    --cpp-bin /path/to/uxas --ada-bin /path/to/uxas_ada
python3 run_differential.py scenarios/heartbeat.json --golden golden/heartbeat.ada.json
python3 run_differential.py scenarios/heartbeat.json --cpp-bin /path/to/uxas --cpp-only
make test-differential                            # from the repo root, see below
python3 -I run_differential.py --self-test        # unit tests, no binaries/zmq
python3 -I -m pytest tests                        # same tests via pytest
```

## CLI

| Option | Meaning |
| --- | --- |
| `scenario` | scenario JSON file |
| `--cpp-bin`, `--ada-bin` | binaries (else `$UXAS_CPP_BIN` / `$UXAS_ADA_BIN`, else `uxas` / `uxas_ada` on `PATH`) |
| `--record-golden FILE` | run the reference side (`--golden-side`, default `ada`), cache its canonical output, then continue to compare with the candidate |
| `--record-only` | with `--record-golden`: stop after recording |
| `--golden FILE` | use a cached reference instead of running Ada (for machines without the Alire/GNAT toolchain) |
| `--ignore-golden-digest` | accept a golden recorded from an older version of the scenario |
| `--cpp-only` | Ada-less smoke mode, see below. Cannot be combined with `--golden`/`--record-golden` |
| `--plugin X` | load a comparator plug-in (`file.py` or module name), repeatable |
| `--workdir DIR` | keep generated configs and process logs there (kept automatically on failure) |
| `--report FILE` | machine readable JSON result |
| `--list-comparators`, `--self-test` | see above |

Exit codes: `0` match, `1` differences, `2` usage/scenario error, `3` a
binary was missing, crashed, exited uncleanly or the timeout hit, `4` golden
file missing/corrupt/stale/for another scenario.

## `make test-differential` and `--cpp-only`

`make test` runs the GoogleTest suite and then `make test-differential`, which
runs `scenarios/heartbeat.json` through `smoke.sh` against `obj/cpp/uxas`.
The reference is chosen in this order:

1. real Ada: `$UXAS_ADA_BIN`, else `uxas_ada` on `PATH` -> full comparison;
2. golden file `golden/heartbeat.ada.json` (override with `$UXAS_GOLDEN`) ->
   comparison against the recorded Ada output (stale/corrupt golden = exit 4);
3. neither -> `--cpp-only`.

`--cpp-only` runs only the C++ side, twice, and checks: both runs are clean
(no crash/unclean exit), the comparator-selected capture is non-empty with no
malformed records (for heartbeat: KeyValuePairs were published back by the
bridge), and the two runs produce identical canonical output (determinism).
It always prints `Ada reference unavailable: parity not checked` and the
report has `parity_checked: false`; it is never a parity pass. Real runs need
`pyzmq` (exit 3 otherwise). Replayed messages default to
`source_entity_id` = the scenario entity id, because the PublishPull bridge
only exports messages whose source entity is its own.

## How a run works

* **C++ side**: one `uxas` with the `LmcpObjectNetworkPublishPullBridge`
  (random free local ports) plus the scenario's services.
* **Ada side**: `uxas_ada` only connects to a bridge hosted by a C++ process
  (it reads `AddressPUB`/`AddressPULL` from the `<Bridge>` element). The
  harness therefore starts a bridge-only C++ `uxas` hub, then `uxas_ada` with
  the *same* `<Bridge>` element plus the services. `binaries.ada.hub` must be
  `"cpp"` (default).
* The harness connects a `SUB` socket to the PUB address and a `PUSH` socket
  to the PULL address. Both binaries are launched as `bin -cfgPath file.xml`
  (override with `binaries.<cpp|ada>.args`, `{CFG}` = config path), in
  their own process group, with stdout/stderr in `<workdir>/<side>/*.log`.
* Schedule (deterministic, no wall-clock heuristics): launch, wait
  `startup_settle_ms` -> for each replay step wait `delay_ms`, send ->
  wait `post_replay_settle_ms` -> stop (SIGINT, SIGTERM, SIGKILL spaced by
  `shutdown_grace_s`). Messages received are tagged with the number of the last
  replayed step. A process dying early, an unclean exit code, `pyzmq` missing,
  or exceeding `timeout_s` fails that side (exit 3, log tail printed).
* The bridge forwards only messages it subscribed to. `capture.subscriptions`
  become `SubscribeToMessage` entries; empty = all (single letter prefixes, as
  pylmcp does).

## Scenario format (JSON)

```json
{
  "name": "heartbeat",
  "description": "free text",
  "entity": {"id": 100, "type": "Aircraft"},
  "root_attrs": {},
  "services": {
    "common": [ {"Type": "RouteAggregatorService", "attrs": {"A": "{WORKDIR}"},
                 "children": [{"tag": "Subscribe", "attrs": {"MessageType": "x"}}]} ],
    "cpp": [], "ada": []
  },
  "binaries": {"ada": {"hub": "cpp", "args": ["-cfgPath", "{CFG}"]}, "cpp": {}},
  "timing": {"startup_settle_ms": 1500, "post_replay_settle_ms": 1500,
             "timeout_s": 60, "shutdown_grace_s": 5},
  "replay": [
    {"label": "hb-0", "delay_ms": 200, "address": "afrl.cmasi.KeyValuePair",
     "frame_hex": "4c4d4350...", "source_entity_id": 100, "source_service_id": 0}
  ],
  "capture": {"subscriptions": ["afrl.cmasi.KeyValuePair"],
              "window": "all", "exclude_echo": false},
  "normalise": {"strip_fields": [], "id_fields": [], "float_digits": 6,
                "exclude_types": [], "keep_entity_id": false},
  "comparator": "heartbeat",
  "comparator_options": {"keys": ["heartbeat"]},
  "plugins": ["my_comparator.py"]
}
```

* `services` may be a plain list (both binaries) or `{common, cpp, ada}`. A
  string entry is shorthand for `{"Type": s}`; elements are `<Service>` by
  default (`"tag"` overrides). Placeholders in attribute values: `{PUB}`,
  `{PULL}`, `{WORKDIR}`, `{ENTITY_ID}`, `{ENTITY_TYPE}`.
* `replay[i]`: `frame_hex` or `frame_b64` is a *complete LMCP frame*
  (control word `LMCP`, size, object header, fields, checksum); `address` is
  required (bus topic, e.g. `afrl.cmasi.KeyValuePair`). Optional: `descriptor`,
  `content_type`, `source_group`, `source_entity_id`, `source_service_id`,
  `delay_ms`, `label`. Frames are validated at load time.
* `capture.window`: `all` sorts everything as one window; `step` keeps the
  messages that arrived after each replay step apart (use when the order of
  replies relative to inputs matters). `exclude_echo` drops captured
  messages whose frame is byte-identical to a replayed frame.
* Plug-in paths ending in `.py` are relative to the scenario file.
* Frames can be generated with `uxdiff.lmcp.build_frame` / `pack_string`, or
  with pylmcp (`Message(obj, ...).pack()` gives the `ADDRESS$attrs$frame`
  envelope; use the part after the second `$`). See
  `scenarios/gen_heartbeat.py`.
* Note: the checksum is verified for information only; the `size` field is
  built as liblmcp does (object bytes incl. the exists byte) and parsed
  tolerantly.

## Normalisation (Design decision 1, approach 1)

Per captured message: parse envelope and LMCP header (series name, type id =
object id, version); decode fields (built-in decoder, else pylmcp if
importable, else raw hex of the field bytes); drop address, source service id,
arrival time, entity id (unless `keep_entity_id`), fields named in
`strip_fields` (default `Time`, `TimeStamp`, `Timestamp`, `TimeReceived`,
`TimeSent`); round floats; sort by (window, canonical content) so arrival order
does not matter; renumber `id_fields` (default `RequestID`, `ResponseID`,
`CorrelationID`, `TaskRequestID`, `PlanningStateID`) as `Name#n` by first
appearance, which preserves request/response linkage but not the values.
Malformed input becomes a `malformed` record (never an exception) and so shows
up as a difference.

Limitation: without pylmcp/e3 only types with a registered decoder
(`uxdiff.normalise.register_decoder`; built in: `CMASI/KeyValuePair`) have
fields stripped; others are compared on raw field bytes, which still contain
ids/times. Install pylmcp's dependencies (`e3-core`) for full decoding, or
register a decoder.

## Comparators (approach 2: plug-ins)

`--list-comparators` shows the registry. Built in:

* `default` - every captured message, strict. Options `include_types`,
  `exclude_types` (descriptors).
* `heartbeat` - only `CMASI/KeyValuePair`, compared as multiset of
  `(Key, Value)`. Options `keys`, `compare_values` (true), `ignore_count`.

Add one (decorator or `register_comparator(name, Class)`):

```python
from uxdiff.comparators import Comparator, register_comparator

@register_comparator("route-aggregator")
class RouteAggregator(Comparator):
    def select(self, rec):            # keep only what this service owns
        return rec["descriptor"].endswith("RoutePlanResponse")
    def project(self, rec):           # reduce to the comparable view
        return {"window": rec["window"], "routes": rec["fields"]["Routes"]}
    # optionally override sort_key(rec) or compare(ref, cand) -> DiffReport
```

Load via `--plugin my_comparator.py` or `"plugins"` in the scenario and select
with `"comparator"`. Inputs are canonical records; `comparators.diff_records`
and `DiffReport` are reusable for custom `compare`.

## Golden files

`--record-golden golden/x.ada.json` stores the canonical records plus the
scenario name and a digest of everything influencing output (entity, services,
replay, capture, normalise). `--golden` refuses files for another scenario or
a changed scenario (exit 4) unless `--ignore-golden-digest`. Record goldens on
a machine with the Ada toolchain and commit them (for the smoke test:
`--record-golden golden/heartbeat.ada.json --record-only`); CI without
Alire/GNAT uses `--golden`. No golden is committed yet (needs the Ada binary).

## Extending for milestones 2-7

1. Write `scenarios/<service>.json`: services config in `services.common`,
   replay frames (AutomationRequest, plans, ...) with realistic delays,
   `capture.subscriptions` for the outputs; prefer `window: "step"` when the
   order of replies matters.
2. Put id/time fields of the service's messages in `normalise.strip_fields` /
   `id_fields`.
3. Add a comparator plug-in if only some outputs are comparable (e.g.
   ignore planning timing, compare plan structure) and register decoders for
   types needed without pylmcp.
4. Record the golden from Ada, commit it, and add a test/CI call.
5. Add unit tests in `tests/` with `FakeBackend` (in-process, virtual clock;
   `uxdiff.backends`) - they must run with `--self-test` alone.

## Layout

`run_differential.py` CLI; `uxdiff/lmcp.py` wire format; `normalise.py`;
`comparators.py`; `scenario.py`; `config.py` XML; `backends.py`
(`ZmqProcessBackend`, `FakeBackend`); `runner.py` driver + goldens;
`scenarios/`; `tests/`.
