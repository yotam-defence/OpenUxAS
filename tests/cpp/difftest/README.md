# difftest: Ada vs C++ differential replay harness

`difftest` replays a recorded LMCP message sequence (a *scenario*) over ZeroMQ
against the Ada reference implementation (`uxas_ada`) and the C++
implementation (`uxas`), captures every message each one publishes, normalises
the *decoded* messages and diffs them. It exits non-zero on mismatch.
Comparison is semantic (decoded LMCP objects), never a byte comparison.

```
scenario.json -> render equivalent XML configs (configs/*.tmpl)
              -> start binary -> settle -> replay steps over PUSH (AddressPULL)
              -> capture on SUB (AddressPUB) -> assign messages to windows
              -> normalise -> compare (comparator registry) -> report/exit code
```

Requirements: Python 3, `pyzmq` and the `pylmcp` package's dependencies
(`e3-core`) for real runs (the same ones `tests/cpp/run-tests` needs). The unit
tests need none of them (only `pytest`).

## Running

```
tests/cpp/run-difftest [options] [scenario.json|dir ...]
# or, from tests/cpp:
python3 -m difftest [options] [scenario.json|dir ...]
```

With no scenario argument all `difftest/scenarios/*.json` run. Binaries are
located from `--ada-bin`/`--cpp-bin`, then `$UXAS_ADA_BIN`/`$UXAS_BIN`, then
`PATH` (`uxas_ada` or `uxas-ada`; `uxas`), then the repo build locations
(`src/ada/uxas-ada`, `obj/cpp/uxas`). Both are started as `<bin> -cfgPath <xml>`.
This harness does not build anything.

| Option | Meaning |
|---|---|
| `--mode auto` (default) | `live` if both binaries are found, else `golden` if the C++ binary and a golden exist, else error |
| `--mode live` | run Ada then C++ (sequentially, on separate free ports) and diff |
| `--mode record-golden` | run Ada only, write `goldens/<scenario>.json` |
| `--mode golden` | run C++ only and diff against the golden |
| `--record-golden` | in live mode also store the Ada output as the golden |
| `--golden-dir DIR` | golden directory (default `difftest/goldens`) |
| `--allow-stale` | accept a golden although the scenario or normaliser config changed |
| `--plugin MOD` | load a comparator plug-in (`.py` path or module), repeatable |
| `--time-scale F` | multiply all delays, windows and settle times (both sides equally) |
| `--startup-settle-ms N` | override the scenario's startup settle |
| `--workdir DIR`, `--keep-workdir` | keep generated configs and `output.log` of each process |
| `--report FILE` | JSON report of all results |
| `--list-comparators` | list registered comparators |
| `-v` | per-window message counts |

Exit codes: `0` all windows match, `1` mismatch, `2` usage, scenario,
golden or infrastructure error (missing binary, process died, ...).

### Golden-file workflow (no Ada toolchain)

On a machine with `uxas_ada`: `run-difftest --mode record-golden` and commit
`goldens/*.json`. Elsewhere `run-difftest --mode golden` (or `auto`) compares
the C++ output with the golden. Goldens contain normalised messages, are
deterministic text (sorted keys), and carry the scenario digest and normaliser
settings; a golden is refused as *stale* if either changed.

## Determinism

* Every step has a *scheduled* time on a timeline anchored when the
  startup settle ends (cumulative `delay_ms` and window durations times
  `--time-scale`). Steps wait for their scheduled time, so send latency does
  not accumulate drift and both implementations see the same schedule.
* Window boundaries are the scheduled times. A received message belongs to the
  first window whose end is >= its receive time. Messages before the timeline
  start are startup noise (dropped, or window `__startup__` with
  `capture_startup`); messages after the last window are reported as a note,
  not compared (`shutdown_settle_ms` gives late output a chance to arrive).
* There is no readiness probe: `startup_settle_ms` is a fixed delay, and the
  harness aborts with the process log tail if the binary has exited by then.
  Raise it (or `--time-scale`) on slow machines.

## Scenario format (JSON)

```json
{
  "name": "smoke",                       // required, no spaces or '/'
  "description": "...",
  "startup_settle_ms": 1500,             // default 1500
  "shutdown_settle_ms": 200,             // default 200
  "capture_startup": false,
  "config": {
    "entity_id": 100, "entity_type": "Aircraft",
    "bridge_subscriptions": ["a", "b"],  // default: every letter a-zA-Z
    "services": [
      {"type": "RouteAggregatorService",                  // or {"ada": "...", "cpp": "..."}
       "attributes": {"Foo": "bar"},
       "children": [{"tag": "Child", "attributes": {"X": "1"}}],
       "impls": ["ada", "cpp"]}                           // optional restriction
    ]
  },
  "normalise": { "strip_fields": [], "renumber_fields": [], "strip_header": [],
                 "float_digits": 6, "ignore_types": [], "replace_defaults": false },
  "comparators": [ {"type": "AirVehicleState", "service": "Sim",
                    "comparator": "float_tolerance", "options": {"rel": 1e-4}} ],
  "services": {"1001": "RouteAggregator"},   // source_service_id -> name
  "steps": [
    {"send": {"type": "KeyValuePair", "fields": {"Key": "k", "Value": "v"},
              "source_entity_id": 100, "source_service_id": 0, "source_group": "",
              "repeat": 5, "interval_ms": 100}},   // "${i}" in strings = repeat index
    {"delay_ms": 100},
    {"expect_window": {"name": "w1", "duration_ms": 500, "ordered": false,
                       "types": ["KeyValuePair"], "min_messages": 0, "max_messages": 10}}
  ]
}
```
(Comments above are illustrative; real JSON has none.)

Each step has exactly one of `send`, `delay_ms`, `expect_window`. The last step
must be an `expect_window`. `send.fields` are pylmcp `Object` attributes;
nested objects use `{"$type": "Name", <field>: ...}`. A window collects every
message observed since the previous window closed. `ordered: true` keeps
arrival order instead of sorting; `types` restricts what is compared;
`min_messages`/`max_messages` are sanity bounds applied to each side
independently. Unknown keys are rejected. Service entries render
`<Service Type=...>` in the config; per-implementation type names allow
the two code bases' naming to differ explicitly.

`scenarios/smoke.json` is the bundled smoke scenario: a heartbeat-style
`KeyValuePair` sequence, no `AutomationRequest`, no services.

## Normalisation (`difftest/normalise.py`)

* Fields named in `strip_fields` are removed at any depth. Defaults: `Time`,
  `TimeSent`, `ReportedTime`, `VehicleTime`, `ScenarioTime`, `TimeLastSeen`,
  `TimeTaskCompleted`, `TimeTaskActivated`.
* Fields in `renumber_fields` (default `CommandID`) are generated ids: values
  are replaced by `<Field#n>` in order of first occurrence across the whole
  capture, so the relation between messages is compared but not the value.
* Header: `source_service_id` is dropped (mapped to a name via `services`);
  other header items (`address`, `content_type`, `source_group`,
  `source_entity_id`) are kept unless listed in `strip_header`.
* Floats are rounded to `float_digits` significant digits; NaN/inf become
  strings, `-0.0` becomes `0.0`; bytes become hex.
* Messages in a window are sorted by (type, canonical content), so arrival
  order is irrelevant (unless `ordered`). `ignore_types` drops message types.
* Undecodable outbound messages become type `__undecodable__` (a finding).

## Comparators (`difftest/comparators.py`)

A comparator is `fn(expected, actual, **options) -> [Difference]` over two
canonical messages. Per message type, messages are first paired when a
comparator deems them equivalent (multiset matching), the leftovers are paired
in canonical order and their differences reported; extras/missing are reported
as `extra_message`/`missing_message` plus a `count` difference.

Resolution order: (type, service) binding > type > service > `default`.
`type` matches the full (`afrl.cmasi.KeyValuePair`) or short name.

Built in: `default` (exact), `float_tolerance` (`rel`, `abs`),
`ignore_fields` (`fields`), `ignore`.

Binding from a scenario (`comparators` list, with `options`) or from code:

```python
# my_plugin.py   -> run-difftest --plugin my_plugin.py
from difftest.comparators import comparator, Difference

@comparator("my_cmp", message_type="AirVehicleState", service="Sim")
def my_cmp(expected, actual, **options):
    return []          # or [Difference("", "value", "fields.X", 1, 2)]
```

A plug-in may also define `register(registry)`. Without `message_type` and
`service` the comparator is only registered by name, for use from a scenario.

## Tests

`pytest tests/cpp/difftest/tests` (no binaries, zmq, pylmcp or e3 needed:
runner logic is tested with a fake capture backend).

## Layout

`cli.py` CLI; `scenario.py`/`model.py` loading and validation; `config.py` +
`configs/` XML rendering; `procs.py` binary lookup and process supervision;
`replay.py` timeline and ZeroMQ transport; `normalise.py`; `comparators.py`;
`golden.py` + `goldens/`; `runner.py` orchestration.
