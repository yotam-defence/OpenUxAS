# difftool - Ada vs C++ differential replay harness

`difftool` is the parity gate between the Ada reference (`uxas_ada`) and the
C++ `uxas`. It starts each with an equivalent XML configuration, replays one
recorded LMCP message sequence over ZeroMQ, captures what comes out, normalises
both captures and diffs them.

The core is standard library only. `pylmcp` (which needs `e3-core`) and `pyzmq`
are imported lazily, only for live replay. `--selftest` and `--compare-files`
run with plain `python3`.

## CLI

```
tests/cpp/run-diff --selftest
tests/cpp/run-diff --scenario FILE [--ada-bin PATH] [--cpp-bin PATH] [--golden DIR]
```

| Option | Meaning |
|---|---|
| `--selftest` | Run the offline unit tests in `difftool/tests/`. |
| `--scenario FILE` | Scenario JSON (see below). |
| `--ada-bin`, `--cpp-bin` | Executables. Both are launched as `BIN -cfgPath CFG.xml`. |
| `--golden DIR` | Golden-file directory. A valid golden file replaces the live Ada run. If none exists and `--ada-bin` is given, the reference is recorded. |
| `--record-golden` | Force a live Ada run and overwrite the golden file. Without `--cpp-bin` it only records. |
| `--allow-stale` | Accept a golden file whose fingerprint no longer matches. |
| `--compare-files ADA.json CPP.json` | Compare two raw capture files; no binaries needed. |
| `--save-captures DIR` | Write raw captures as `ada.json` / `cpp.json`. |
| `--report FILE` | Also write the JSON report. |
| `--plugin MOD_OR_PY` | Load a comparator plug-in (repeatable). |
| `--list-comparators` | List registered comparators. |
| `--log-dir DIR` | Keep stdout/stderr of the launched binaries. |

Exit codes: `0` match, `1` differences, `2` usage or scenario error,
`3` infrastructure error (binary missing or died, ZeroMQ or pylmcp missing),
`4` golden file missing or stale.

Typical flows:

```
# machine with Alire/GNAT: record the reference once, then compare
tests/cpp/run-diff --scenario S.json --ada-bin uxas_ada --cpp-bin uxas --golden tests/cpp/difftool/golden
# CI without Ada: compare C++ against the cached reference
tests/cpp/run-diff --scenario S.json --cpp-bin uxas --golden tests/cpp/difftool/golden
```

## Topology

Both stacks expose a `LmcpObjectNetworkPublishPullBridge` (default
`tcp://127.0.0.1:5560` PUB, `5561` PULL). The harness is a ZeroMQ client: it
PUSHes replayed messages to the PULL address and SUBscribes to the PUB address.

* C++ side: `uxas -cfgPath cpp_cfg`.
* Ada side: `uxas_ada` has no bus of its own; it connects as a client to the
  bridge of a C++ process. If `ada_hub_cfg` is set the runner first starts
  `--cpp-bin` with that config (the hub hosting the bus), then
  `uxas_ada -cfgPath ada_cfg`. The harness taps the same bridge.

Sides run sequentially (not concurrently) so they can share ports, and every
process is stopped with SIGINT (then kill) afterwards.

## Scenario format (JSON)

Relative paths are resolved against the scenario file.

| Key | Required | Description |
|---|---|---|
| `name` | yes | Identifier; names the golden file. |
| `ada_cfg`, `cpp_cfg` | yes | XML configs for the two binaries. |
| `ada_hub_cfg` | no | XML for the C++ hub hosting the Ada bus. |
| `messages` | yes | Replay list, see below. |
| `startup_delay_ms` | no (1000) | Wait after starting processes. |
| `settle_ms` | no (1000) | Wait after the last message before capture ends. |
| `capture` | no (`[""]`) | ZeroMQ SUB prefixes (addresses). `""` = everything. |
| `endpoint` | no | `{"pub": ..., "push": ...}` override. |
| `normalization` | no | See normalisation options. |
| `comparators` | no (`canonical`) | List of names or `{"name": ..., options}`. |
| `plugins` | no | Comparator plug-in modules or `.py` paths (relative to the scenario). |
| `description` | no | Free text. |

Message entry:

```json
{"class": "KeyValuePair", "delay_ms": 100,
 "fields": {"Key": "heartbeat", "Value": "seq-0"},
 "source_entity_id": 100, "source_service_id": 0}
```

`delay_ms` is waited before sending. `class` is resolved by `pylmcp` (partial
names accepted). `fields` are passed to the pylmcp `Object`; a nested object is
a dict with a `"_class"` key. Optional `source_group` and `address`.

See `scenarios/heartbeat_smoke.json`: five `KeyValuePair` heartbeats, no
`AutomationRequest`, with matching XML configs for both binaries.

## Normalisation rules

Captures are raw dicts (`t_ms`, header, decoded `obj`). Canonicalisation:

1. **Order and window.** Sort by capture time; start a new window when the gap
   to the previous message exceeds `window_ms` (default 200). `0` keeps strict
   arrival order, `null` makes one window.
2. **Sort inside each window** by (type, body with ids stripped), so legitimate
   reordering of concurrent outputs is not a difference.
3. **Strip timestamps.** Fields matching `strip_fields` (case-insensitive full
   regexes; defaults cover `Time`, `TimeStamp`, `*Time*stamp`, ...) are removed
   at any depth.
4. **Ids** (`id_fields`, default `RequestID`, `ResponseID`,
   `UniqueAutomationRequestID`, ...): `id_mode` is `renumber` (default; values
   become `<id:N>` per field name in sorted order, 0 is kept), `strip`, or
   `keep`.
5. **Header.** `source_service_id` is ignored by default (`ignore_header`);
   address, descriptor, content type, source group and entity id are compared.
6. **Floats** are rounded to `float_digits` (default 6, `null` = exact);
   `-0.0` folds to `0.0`. Bytes become hex.

`extra_strip_fields` / `extra_id_fields` extend the defaults without replacing
them.

## Comparators

| Name | Behaviour |
|---|---|
| `canonical` (default) | Window by window multiset equality of canonical messages; reports missing/extra messages and field-level mismatches (`body.Value`: ada vs cpp). |
| `count` | Per-type message counts only. |
| `types` | Set of message types only. |
| `superset` | Every Ada message must appear in the C++ output; extras allowed (incomplete ports). |
| `field_subset` | `canonical` restricted to `fields` (top-level body names). |

All accept `include` / `exclude` fnmatch lists on the message type, e.g.
`{"name": "canonical", "include": ["*AssignmentCostMatrix"]}`; several
comparators can be listed and all must pass, which gives per-service
strictness (strict on a service's outputs, `types` on the rest).

Plug-in:

```python
from difftool import comparators, report

@comparators.register("my_service")
class MyService(comparators.Comparator):
    def compare_windows(self, ada_windows, cpp_windows):   # lists of lists of Canonical
        return []                                          # list of report.Difference
```

Load it with `--plugin my_plugin.py` or `"plugins": ["my_plugin.py"]`.

## Golden files

`DIR/<scenario>.ada.golden.json` stores the **raw** (pre-normalisation) Ada
capture plus a fingerprint (hash of Ada config, hub config, messages, capture
list, endpoint and delays; the C++ config is excluded). Raw storage means
normalisation changes need no re-recording. A changed fingerprint makes the
file stale (exit 4) unless `--allow-stale`. Commit golden files like test data.

## Design decisions

* **Canonical diff as the default (option 1), plug-ins as extension (option 2),
  no byte comparison (option 3).** Ada and C++ legitimately differ in ids,
  timestamps, service ids and concurrent ordering; byte comparison would be
  flaky and meaningless. Canonical comparison is strict about content but
  tolerant of those. Per-service plug-ins and `include`/`exclude` let service
  milestones relax or tighten per message type without changing the core.
* **Ids are renumbered, not just stripped,** so a C++ service that breaks a
  request/response correlation still fails, while concrete id values do not.
* **Gap-based windows instead of fixed buckets:** fixed boundaries can split
  the same burst differently on the two sides; gaps are stable given settle
  delays. Caveat: a gap near `window_ms` can still change window counts, so
  choose `window_ms` well below inter-burst delay (or `null` for unordered
  scenarios).
* **Golden files** cache Ada output because Alire/GNAT may be unavailable.
* **Deterministic replay:** fixed delays, a startup delay and a settle delay
  instead of polling; sides run sequentially.
* **Injectable launcher/transport** keep runner and CLI logic testable offline.

## Layout

`scenario.py` parsing, `normalize.py`, `comparators.py`, `report.py`,
`golden.py`, `runner.py` (process control, orchestration), `live.py` (ZeroMQ +
pylmcp, lazy), `cli.py`, `tests/`, `scenarios/`.

## Known limitations

* Live replay was not exercised in this environment (no `e3`, `pyzmq`, built
  binaries or Ada toolchain); it is covered through fakes only.
* The Ada binary requires a C++ hub, so `--cpp-bin` is needed for the Ada side
  when `ada_hub_cfg` is used.
* Window alignment between sides is by index (see design decisions).
