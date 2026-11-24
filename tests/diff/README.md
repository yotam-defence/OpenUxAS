# uxas_diff: Ada vs C++ differential replay harness

Starts the Ada reference (`uxas_ada`) and the C++ `uxas` with equivalent XML
configs, replays one LMCP message sequence into each over ZeroMQ, captures
the outbound LMCP messages, canonicalises them and diffs. The result is the
parity gate for the Ada-to-C++ port.

Python 3 standard library only. `zmq` and `pylmcp` (which needs the `e3`
package, same as `tests/cpp/run-tests.py`) are imported lazily, only by
commands that talk to a running binary. Unit tests, `canon` and `diff`
need none of them. `run --golden` skips the Ada side but still has to start
the C++ binary, so it needs `uxas`, zmq,
pylmcp and e3.

Placement: `tests/diff` is a sibling of `tests/cpp`, and imports the
`pylmcp` package from `tests/cpp/pylmcp` (override the directory containing
`pylmcp` with `$PYLMCP_PATH`; the default is `tests/cpp`). `make test` runs
the unit tests and the golden smoke run (`make diff-unit-tests`,
`make diff-smoke`); the smoke run is skipped with a message only when
`e3-core`/`pyzmq` are not installed.

Run from this directory (`tests/diff`) or put it on `PYTHONPATH`.

## CLI

    python3 -m uxas_diff run SCENARIO [--golden] [--uxas-bin P] [--ada-bin P]
                          [--report out.json] [--save-captures DIR] [--keep-dir DIR]
    python3 -m uxas_diff record SCENARIO [--impl ada|cpp] [--golden-dir DIR]
    python3 -m uxas_diff canon CAPTURE.json [--scenario SCENARIO]
    python3 -m uxas_diff diff REF.json TEST.json [--scenario SCENARIO]

`SCENARIO` is a directory (or its `scenario.json`) or a name under
`scenarios/`. All commands accept `--plugin MODULE_OR_FILE.py` (repeatable).

* `run`: run Ada and C++, diff. With `--golden` the Ada side is read from
  `golden/<scenario>.json` and only C++ is run (no Ada toolchain needed).
* `record`: run the Ada reference and write `golden/<scenario>.json`.
* `canon`: print the canonical form of a capture/golden file.
* `diff`: offline diff of two capture files (no binaries).

Exit status: `0` match, `1` mismatch, `2` usage/environment error (missing
binary or golden, bad scenario, process died).

Binaries: `--uxas-bin` / `$UXAS_BIN` (C++ `uxas`), `--ada-bin` /
`$UXAS_ADA_BIN` (`uxas_ada`), else looked up on `PATH`.

## Comparison strategy (design decision)

Of the three options (canonical decoded diff, per-service comparators,
byte-for-byte) the harness uses **canonicalised decoded messages as the
default, with per-service comparator plug-ins as an override**. Byte-for-byte
comparison is deliberately **not** used: Ada and C++ legitimately differ in
message ids, timestamps, source service ids and emission order, so it would
be flaky and would block deleting Ada for irrelevant reasons.

Canonicalisation (`uxas_diff/canon.py`), applied to decoded LMCP objects
(pylmcp `Message.unpack`), never to raw bytes:

1. drop transport metadata: source entity/service ids, source group, timing;
2. strip volatile fields at any depth (`strip_fields`, default `Time`,
   `TimeStamp`, ...);
3. replace run-specific ids (`renumber_fields`, default `RequestID`,
   `ResponseID`, `CommandID`, `PlanID`, ...) by first-appearance ordinals
   `<id:N>`, so cross references between messages stay checked but concrete
   values are ignored (ordinals are assigned after sorting on id-masked
   bodies, so they do not depend on arrival order);
4. drop unset values (`None`, `[]`, `""`) and round floats to
   `float_digits` (6) significant digits (float32 vs float64 safe);
5. assign each message to a window and sort by `(window, type, body)`.
   `window` is `"phase"` (messages are bucketed by the replay step that
   preceded their arrival: deterministic, recommended), `"all"` (one
   window: pure multiset comparison) or an integer N (N ms time buckets,
   timing-dependent, use sparingly).

Comparators (`uxas_diff/comparators.py`): after canonicalisation messages
are grouped by type; each type is compared by the comparator chosen via the
scenario `comparators` map (exact type, then first matching glob, then
`canonical`). Built-ins: `canonical` (multiset equality, default), `count`
(per-window counts only), `ignore`. Service milestones add their own:

    # my_plugin.py  (scenario "plugins": ["my_plugin.py"] or --plugin)
    from uxas_diff.comparators import comparator

    @comparator("route_cost_within_1pct")
    def route_cost_within_1pct(ref, test, ctx):
        # ref/test: canonical messages of one type; return [] if equal,
        # else a list of mismatch descriptions.
        ...

Per-type filtering is also available through `canon.only_types` /
`canon.ignore_types`.

## Scenario format

JSON (stdlib only, no YAML dependency). A scenario directory contains
`scenario.json` plus the XML configs it references:

    {
      "name": "smoke_heartbeat",                  // must equal golden file name
      "configs": {"ada": "cfg_ada.xml",           // config for uxas_ada
                  "cpp": "cfg_cpp.xml",           // equivalent config for uxas
                  "hub": "cfg_hub.xml"},          // optional, Ada only (below)
      "startup_settle_ms": 2000,                  // wait for SUB/PUSH connect
      "messages": [                               // replayed in order
        {"delay_ms": 200, "label": "x",
         "object": {"class": "afrl.cmasi.AirVehicleState",
                    "fields": {"ID": 400,
                               "Location": {"class": "afrl.cmasi.Location3D",
                                            "fields": {...}}}}},
        {"delay_ms": 0, "hex": "<full wire message as hex>"},
        {"delay_ms": 500}                         // pure settle step
      ],
      "capture": {"tail_ms": 1500},               // keep capturing after last step
      "canon": {"window": "all"},                 // overrides of canon defaults
      "comparators": {"afrl.cmasi.*": "canonical"},
      "plugins": []
    }

Each step waits `delay_ms` (still capturing) and then sends. `object`
steps are built with pylmcp `Object` (unset fields get zero values) and
wrapped in a `Message` with entity id 100; `hex` steps are sent verbatim.
The capture window starts at launch of the replay (after
`startup_settle_ms`) and ends `capture.tail_ms` after the last step.

Config files may use the placeholders `${PUB_PORT}` and `${PULL_PORT}`;
the runner picks free ports per run so Ada and C++ runs never collide.

Why a `hub` config: `uxas_ada` hosts only Ada services and reads the
`LmcpObjectNetworkPublishPullBridge` addresses from its config to attach
to a C++ `uxas` that owns the bridge sockets (see
`src/ada/src/main/uxas_ada.adb` and `examples/02a_Ada_WaterwaySearch`).
For the Ada run the runner therefore starts `uxas` with `cfg_hub.xml`
first, then `uxas_ada` with `cfg_ada.xml`; for the C++ run it starts only
`uxas` with `cfg_cpp.xml`. The harness always observes the bridge's PUB
socket and pushes into its PULL socket.

## Captures and goldens

Records (`golden/<scenario>.json`, key `messages`) hold decoded messages
(`descriptor`, `obj`, `phase`, `t_ms`, source ids, ...). Goldens store the
raw decoded capture, not the canonical form, so canonicalisation rules can
evolve without re-recording. Golden metadata has `provenance`:
`recorded` (from a real Ada run) or `synthetic`.

**The shipped `golden/smoke_heartbeat.json` is `synthetic`**: it was
generated without an Ada toolchain by encoding/decoding the scenario
messages through pylmcp, i.e. it encodes the expectation that the bridge
echoes each replayed message and the validator emits nothing for
heartbeats. `run --golden` prints a warning for synthetic goldens. Replace
it on a machine with the Ada build:

    UXAS_BIN=... UXAS_ADA_BIN=... python3 -m uxas_diff record smoke_heartbeat

**Known gap: the golden is synthetic. Re-record with
`record smoke_heartbeat` once the Ada toolchain is available (milestone 2
task).** Until then the smoke run only checks that the C++ `uxas` matches
the expectation encoded in the synthetic golden, not real Ada behaviour.

## Smoke scenario

`scenarios/smoke_heartbeat`: one `AirVehicleConfiguration` and three
`AirVehicleState` messages with the `AutomationRequestValidatorService`
running; no `AutomationRequest`, no `KeyValuePair` entries.

## Unit tests

    python3 -m unittest discover -s tests          # from tests/diff
    # or: python3 -m pytest tests

No binaries, zmq, pylmcp or e3 required (the replay loop is tested with a
mock transport and fake clock).

## Adding a scenario

Create `scenarios/<name>/` with `scenario.json`, the cfg files, run
`record`, review and commit `golden/<name>.json`.
