# diffharness: Ada-vs-C++ differential replay harness

Runs the same scenario against the C++ `uxas` and the Ada `uxas_ada`, captures
the outbound LMCP of each over ZeroMQ, canonicalises it and prints a unified
diff. Exit code: `0` equivalent, `1` mismatch, `2` usage/environment error.

It lives next to `pylmcp` and reuses its `Message`/`Object` codec and the
`PublishPullBridge` mechanism of `pylmcp/uxas.py`.

## Requirements

* Always: Python 3.8+.
* Unit tests: `pytest` only (no binaries, no pyzmq, no e3).
* Replaying against binaries: `pyzmq` and `e3-core` (needed by `pylmcp`).
  Both are imported lazily; a missing one gives an explicit error (exit 2).
* YAML scenarios: `pyyaml` (JSON needs nothing).

## CLI

    tests/cpp/run-diff   --cpp-bin PATH --ada-bin PATH --scenario smoke_heartbeat
    python -m diffharness ...        # with tests/cpp on PYTHONPATH

| option | meaning |
|---|---|
| `--cpp-bin`, `--ada-bin` | executables (`uxas`, `uxas_ada`); started with `-cfgPath <generated xml>` |
| `--scenario` | file path or bare name in `scenarios/` |
| `--golden-dir` | cached captures (default `diffharness/golden`) |
| `--update-golden` | store captures of the binaries run as golden files |
| `--reference golden` | no Ada toolchain: use the cached Ada golden as the reference; only `--cpp-bin` is needed |
| `--settle-delay S` | seconds to wait after launch before replaying (default 2) |
| `--plugin MODULE` | import a module that registers comparators (repeatable) |
| `--list-comparators`, `--dry-run`, `--context N` | list comparators; print generated configs only; diff context |

Typical flows:

    # live, both binaries
    run-diff --cpp-bin obj/cpp/uxas --ada-bin obj/ada/uxas_ada --scenario smoke_heartbeat
    # Ada not buildable here
    run-diff --cpp-bin obj/cpp/uxas --reference golden --scenario smoke_heartbeat
    # (re)record goldens
    run-diff --cpp-bin ... --ada-bin ... --scenario X --update-golden

## Scenario format (JSON, or YAML with the same keys)

    {
      "name": "smoke_heartbeat",            // required; golden subdir name
      "description": "...",
      "entity_id": 100, "entity_type": "Aircraft", "run_duration_s": 60,
      "bridge": {"pub": "tcp://127.0.0.1:5560", "pull": "tcp://127.0.0.1:5561"},
      "services": [                         // generated into BOTH configs
        {"Type": "AutomationRequestValidatorService"},
        {"Type": "WaypointPlanManagerService", "VehicleID": 400,
         "impl": "ada"}                     // optional: only for "ada"/"cpp"
        // "tag": "Bridge" for non-Service elements, "children": [...] nested
      ],
      "capture": {"subscribe": ["afrl.cmasi.KeyValuePair"],   // or ["*"]
                  "quiet_ms": 1000, "max_wait_ms": 10000,
                  "ignore_types": []},
      "replay": [
        {"delay_ms": 0, "type": "KeyValuePair",
         "fields": {"Key": "heartbeat", "Value": "1"}},
        {"delay_ms": 100, "raw_b64": "<packed LMCP object>",
         "address": "afrl.cmasi.Foo"}     // raw payload alternative
        // optional per step: source_entity_id, source_service_id, source_group
      ],
      "comparator": "canonical"
        // or {"name": "...", "options": {"normalise": {...}},
        //     "by_type": {"afrl.cmasi.Foo": {"name": "..."}}}
    }

`delay_ms` is relative to the previous step. Nested LMCP objects in `fields`
are written `{"$type": "afrl.cmasi.Location3D", ...}`. The same XML dialect is
used by both binaries (see `examples/02d_Ada_WPM_WaterwaySearch/cfg_{ada,cpp}.xml`);
the harness appends a `LmcpObjectNetworkPublishPullBridge` subscribed to the
capture types. Capture is the bridge PUB feed, which also echoes the injected
messages when they are subscribed to.

## Normalisation (design decision: canonicalise)

Byte-exact comparison is not meaningful between two implementations, so
records are canonicalised (`normalise.py`):

* fields matching timestamp/entity-id-time patterns are removed; envelope
  `source_service_id`, `source_group`, arrival time are dropped;
* generated ids (`ResponseID`, `CommandID`, `PlanID`) are renumbered in order
  of appearance: correlation is checked, concrete values are not;
* floats rounded to 6 digits, `-0.0` folded;
* within a time window (`window_ms`, 0 = single window) messages are sorted by
  (type, canonical content), so thread interleaving does not matter, while
  ordering across windows does.

Options go in `comparator.options.normalise`: `strip_fields` (regexes),
`extra_strip_fields`, `remap_fields`, `strip_envelope`, `float_digits`,
`window_ms`, `sort`, `ignore_types`.

## Comparator plug-ins (for services in later milestones)

Registry in `comparators.py`. Built in: `canonical` (default), `strict`
(no stripping/sorting; harness debugging). Add one:

    from diffharness.comparators import Comparator, register_comparator

    @register_comparator("waypoint_plan")
    class WaypointPlan(Comparator):
        def normalise(self, records):   # plain records -> normalised list
            ...
        def render(self, normalised):   # -> list[str], the text that is diffed
            ...
        def equivalent(self, expected, actual):  # default: equality
            ...

Make it discoverable via `diffharness/comparators_ext/` (auto-imported if
present), `--plugin module`, or `DIFFHARNESS_PLUGINS=mod1,mod2`. Select it
in a scenario by name; `by_type` routes individual message types to different
comparators and diffs them in separate sections.

## Golden files

`golden/<scenario>/<impl>.json` hold decoded but un-normalised records
(`format`, `provenance`, `records`), so normaliser changes need no
re-recording. The committed `smoke_heartbeat` goldens are recorded from real binaries
(see below).

## Flakiness mitigation

* `--settle-delay`: binary launch is followed by a quiet period; traffic seen
  during it is discarded and nothing is sent until it elapses. Increase on
  loaded CI.
* Deterministic replay: messages are pre-encoded and sent from one thread on
  a monotonic schedule (`delay_ms` is relative so drift does not accumulate);
  capture shares that thread/clock.
* Capture ends after `quiet_ms` without traffic (bounded by `max_wait_ms`),
  never after a fixed sleep.
* Sorting inside windows, id renumbering and stripping of volatile fields.
* Fixed ports by default: run one harness at a time or set `bridge.pub/pull`
  per scenario. Binaries get SIGINT, then SIGTERM, then SIGKILL.

## Tests

    cd tests/cpp && python3 -m pytest diffharness/tests

## Not covered / known gaps

* Live smoke runs against both binaries have been exercised; no scenario with
  Ada-hosted services has been run yet.
* No service-specific comparators yet (milestones 3-6).
* Wired into the Makefile (`make diff-smoke`, part of `make test`) and the CI workflow.

## Ada reference goldens and their limits

`golden/smoke_heartbeat/{ada,cpp}.json` are **recorded** from real binaries
(see each file's `provenance`: binary hashes, toolchain, date). The Ada
reference is `uxas_ada` built with GNAT FSF 14.2.0 and the gnatprove 14.1
SPARKlib (lifecycle script `ada-reference`, output
`$WORKSPACE_DIR/.ada-build/uxas-ada`; `./anod build uxas-ada` is the
upstream route). The distro GNAT 14.3 with gnatprove 13.2 does not compile the
sources (`unconstrained subtype in component declaration`: 13.x formal maps are
discriminated); the build also drops SPARKlib's `Aggregate` aspect on formal
vectors/lists in a private copy because GNAT 14.2 rejects it.

`uxas_ada` is not a standalone node: it only hosts Ada services and connects
as a client to the bridge of a C++ `uxas`, and exits at once if it has no
services. An Ada run therefore starts the C++ `uxas` as hub (config role
`hub`: bridge plus services without an `impl` filter) and then `uxas_ada`
(services with `impl: "ada"` plus the same bridge addresses). Pass `--cpp-bin`
for both.

Limitation: `smoke_heartbeat` configures no services, so the Ada process
contributes nothing and the Ada golden equals the bridge echo; it proves the
toolchain/plumbing, not Ada service behaviour. Service scenarios (milestones
3-6) need `impl: "ada"` services to exercise Ada. Re-record with
`run-diff ... --update-golden [--ada-build-note TEXT]`; use
`make diff-smoke ADA_BIN=<path>` for a live comparison.
