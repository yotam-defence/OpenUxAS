# Differential replay harness (`tests/cpp/run-diff`)

Starts the Ada reference `uxas_ada` and the C++ `uxas` with equivalent XML
configurations generated from a *scenario*, replays the same recorded LMCP
message sequence over ZeroMQ, captures what each implementation publishes,
normalises the captures and diffs them.  Service milestones (3-6) add
scenarios and comparators here; milestone 7 uses it as the gate for deleting
the Ada tree.

```
scenario.json --> config.py --> cfg_ada.xml / cfg_cpp.xml
                                  |                |
        HubBus (harness binds)  <-+  uxas_ada      +-> uxas  <-> ClientBus
                  \________ replay the same frames ________/
                  capture (raw frames, windowed, echo-filtered)
                       |                              |
                 golden file (Ada)  --or--  live      live (C++)
                       \_______ canonicalise + comparators _______/
                                         diff report / exit code
```

## Usage

```
tests/cpp/run-diff run smoke_heartbeat              # scenario name, or a path
tests/cpp/run-diff run --all                        # every scenarios/*.json
tests/cpp/run-diff run smoke_heartbeat --uxas build/uxas --uxas-ada build/uxas_ada
tests/cpp/run-diff run smoke_heartbeat --update-golden     # record golden files (needs both binaries)
tests/cpp/run-diff run smoke_heartbeat --ada golden        # CI without Alire/GNAT
tests/cpp/run-diff gen-config smoke_heartbeat ada          # print generated XML
tests/cpp/run-diff record out.jsonl --sub-url tcp://127.0.0.1:5560 --duration 20
tests/cpp/run-diff show pylmcp/diff/golden/smoke_heartbeat.ada.json
```

Binaries: `--uxas` / `--uxas-ada`, else `$UXAS_BIN` / `$UXAS_ADA_BIN`, else
`uxas` / `uxas_ada` on `PATH`.  Python needs `pyzmq` (live runs only) and the
dependencies of `pylmcp` (`e3` is optional for this package).

Reference source (`--ada`, `--cpp`): `live` runs the binary; `golden` reads
`golden/<scenario>.<side>.json`; `auto` (Ada default) uses a golden file when
it exists and is fresh, else runs live.  Golden files store the *raw frames*,
so changing normalisation/comparators never requires re-running Ada.  A
golden file records a fingerprint of everything that affects the raw capture
(services, replay, timing, bus, echo filter, window mode); a stale golden is
rejected unless `--allow-stale-golden`.

Exit codes: `0` match, `1` mismatch, `2` usage/scenario error, `3`
infrastructure error (binary missing, process died, no golden file).
`--report FILE` writes a JSON report; `-v` logs the steps; `--workdir DIR`
keeps generated configs and process logs.

## Determinism

* Sides run sequentially on the same ports (`bus` in the scenario).
* `timing.startup_ms` before the first message; after each injected message
  the harness waits `settle_ms` (per-step override) collecting output; a
  final `drain_ms`.  Output is attributed to the *window* of the step whose
  settle period it arrived in (window 0 = startup, window *i* = step *i*),
  so results do not depend on wall-clock bucket edges.
* Ada connects to the bridge addresses (see `uxas_ada.adb`), therefore for
  the Ada side the harness binds XPUB+PULL and relays PULL->PUB like the C++
  bridge; for C++ the harness connects SUB+PUSH to the bridge `uxas` binds.
* The C++ bridge echoes injected messages back; the *echo filter*
  (`capture.echo_filter`: `bytes` | `envelope` | `none`) drops them so both
  sides capture only service output.

## Normalisation (design option 1)

Applied to decoded LMCP messages (`canonical.py`):

1. fields matching `strip_fields` (default `Time`, `TimeStamp`, `Timestamp`,
   `*TimeStamp`, `*Timestamp`, `LastTime`) are dropped recursively;
2. fields matching `id_fields` (default `RequestID`, `ResponseID`,
   `TaskRequestID`, `CommandID`) are dropped (`id_mode: strip`) or replaced by
   first-appearance ordinals (`id_mode: remap`, keeps cross-references
   checked and is independent of arrival order);
3. floats rounded to `float_digits` (default 6);
4. source service id dropped (`keep_service_id`), source entity kept
   (`keep_source_entity`);
5. messages sorted by (type, canonical text) inside each window.

## Comparators (design option 2 extension point)

Messages of each window are routed by the first matching `comparators` rule
(glob on full or short type name) to a comparator; unmatched types use
`exact` (multiset equality of canonical messages).  Built-ins: `exact`,
`ignore`, `types_only` (counts per type), `tolerance` (`abs`/`rel` numeric
tolerance).  All accept `ignore_fields`.  Custom plug-ins subclass
`pylmcp.diff.comparators.Comparator`, implement
`compare(window, ref, got) -> [Difference]` and are referenced as
`"my.module:Class"` or `"/path/plug.py:Class"` in `use`.  Byte-for-byte
comparison (option 3) is intentionally not offered.

## Scenario file format (JSON, `format_version` 1)

Strict: unknown keys are errors.  Only `format_version` and `name` are
required.

```json
{
  "format_version": 1,
  "name": "smoke_heartbeat",              // no spaces or slashes
  "description": "free text",             // (no comments in real JSON files)
  "entity": {"id": 100, "type": "Aircraft"},
  "bus": {"pub": "tcp://127.0.0.1:5560", "pull": "tcp://127.0.0.1:5561"},
  "services": [
    {"type": "RouteAggregatorService",
     "attributes": {"FooBar": 1, "Flag": true},      // bool -> TRUE/FALSE
     "children": [{"tag": "Sub", "attributes": {}, "children": []}],
     "sides": ["ada", "cpp"]}                         // default both
  ],
  "timing": {"startup_ms": 2000, "settle_ms": 300, "drain_ms": 500, "shutdown_ms": 3000},
  "replay": [
    {"label": "x", "delay_ms": 0, "settle_ms": 300,
     "lmcp": {"type": "afrl.cmasi.KeyValuePair",
              "fields": {"Key": "k", "Value": "v"},
              "source_entity_id": 100, "source_service_id": 0, "source_group": ""}},
    {"frame_hex": "<raw frame hex>"},
    {"recording": "recordings/foo.jsonl"}              // expands in place
  ],
  "capture": {"echo_filter": "bytes", "window": "step", "min_messages": 0,
              "exclude_types": ["afrl.cmasi.SessionStatus"]},
  "normalise": {"strip_fields": [], "id_fields": [], "id_mode": "strip",
                "float_digits": 6, "keep_service_id": false, "keep_source_entity": true},
  "comparators": [
    {"match": ["afrl.cmasi.Route*"], "use": "tolerance",
     "options": {"abs": 0.001}, "service": "RouteAggregatorService"}
  ]
}
```

* `lmcp.fields`: nested LMCP objects are written `{"@type": "afrl.cmasi.Location3D", ...}`
  (lists of them allowed); types accept pylmcp partial names.
* `capture.window`: `step` (default), `all` (order-insensitive over the whole run),
  `fixed:<ms>` (wall-clock buckets, less deterministic).
* `min_messages`: each side must produce at least this many messages (guards
  against a vacuous "both empty" match).
* Recording files (`run-diff record`) are JSON lines
  `{"delay_ms": N, "frame_hex": "..."}`; `#` comment lines are allowed.
* `services[].sides` lets a scenario enable a service on one side only (e.g.
  a C++ service that has no Ada counterpart).

The shipped smoke scenario `scenarios/smoke_heartbeat.json` replays three
`KeyValuePair` heartbeats (no `AutomationRequest`) against an
`AutomationRequestValidatorService` configuration; both outputs must match.
It sets `min_messages: 0`, i.e. it currently proves the harness plumbing and
"no unexpected output", not behavioural parity.

## Tests

```
python3 -I -m pytest tests/cpp/pylmcp/diff/tests
```

The tests need neither binaries nor ZeroMQ: `testing.py` provides
`FakeLauncher`/`FakeProcess`/`FakeBus`/`FakeClock` (virtual time), which are
also meant for service milestones' own comparator tests.

## Known limits

* Never run against real binaries in this repository's sandbox (none built);
  live paths (`bus.py`, `process.py`) are exercised only by the fakes.
* Both sides use the same ports sequentially; run one harness at a time.
* Service-id based filtering of output is not offered; use `exclude_types`.
