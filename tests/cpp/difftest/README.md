# difftest: Ada vs C++ differential replay harness

Starts the Ada reference `uxas_ada` and the C++ `uxas` with equivalent XML
configurations generated from one scenario, replays the same LMCP message
sequence over ZeroMQ, captures what each publishes, normalises the captures
and diffs them. It is the parity gate for the Ada to C++ migration.

```
cd tests/cpp
python3 -m difftest scenarios/smoke_heartbeat.json --ada-bin /path/uxas_ada --cpp-bin /path/uxas
```

Dependencies: Python 3.8+, `pyzmq` (replay only), `pylmcp` + `e3` (already
required by `tests/cpp/pylmcp`; used to encode/decode LMCP). The scenario,
normaliser, comparators, golden and report modules are pure Python and the unit
tests need no binaries, pyzmq or pylmcp.

## CLI

| option | meaning |
|---|---|
| `scenario` | scenario JSON |
| `--ada-bin`, `--cpp-bin` | binaries (else `$UXAS_ADA_BIN` / `$UXAS_CPP_BIN`, else `uxas_ada` / `uxas` on PATH) |
| `--record-golden` | run Ada, store capture in the golden file, then compare C++ (`--record-only` stops after recording) |
| `--use-golden` | do not run Ada; compare C++ with the stored golden capture |
| `--golden-dir` | default `<scenario dir>/golden` (`$DIFFTEST_GOLDEN_DIR`); file `<name>.ada.golden.json` |
| `--allow-stale-golden` | accept a golden whose scenario fingerprint no longer matches |
| `--plugin MODULE` | import a module registering comparators (repeatable) |
| `--report-json FILE` | machine readable report |
| `--time-scale F` | multiply all settle delays (slow CI) |
| `--workdir DIR` | keep generated configs and `ada.log`/`cpp.log` |
| `--pub/--pull` | override bridge addresses |
| `--dump-config ada\|cpp`, `--validate`, `--list-comparators` | inspection helpers, no binaries needed |

Exit codes: `0` match, `1` differences, `2` usage/scenario error, `3`
infrastructure error (binary missing/died, pyzmq missing, golden missing/stale).

Ada and C++ run one after the other on the same bridge ports (a run is
deterministic and never races the other binary). Both are started with
`-cfgPath <file>`.

## Scenario format (JSON)

See `scenarios/smoke_heartbeat.json` and the docstring of `scenario.py`.
Keys: `name`, `description`, `entity_id`, `entity_type`, `bridge{pub,pull}`,
`subscribe` (bridge SubscribeToMessage prefixes, default a-zA-Z), `services[]`
(`type`, `attributes`, `children[]`, `kind` Service|Bridge, `only` ada|cpp for
legitimately different config), `settle{startup_s, between_messages_s,
final_s}`, `messages[]` (`lmcp{type,fields}` encoded with pylmcp, or `hex` =
complete wire message `address$content|descriptor|group|entity|service$payload`;
optional `delay_s`, `source_entity_id`), `normalise`, `comparators`, `plugins`.

## Comparison strategy (design decision 1)

Canonicalisation (approach 1) is the default; per-service comparators
(approach 2) plug in on top; byte-for-byte (approach 3) is not used.

* Capture records carry `step` = number of scenario messages injected when the
  message arrived. A *window* is one step, so ordering is only ignored between
  messages answering the same stimulus (`normalise.window: "all"` merges all).
* Dropped: raw bytes, capture time, source service id, fields whose names match
  `time_keys` (timestamps), `ignore_keys`, descriptors matching `ignore_types`.
* Identifiers (`id_keys`) are `renumber`ed by first appearance in canonical
  order (keeps cross-message linkage, ignores actual values), `strip`ped or
  `keep`t (`id_mode`). Floats are rounded (`float_digits`).
* Within a window messages are sorted by type then id-masked content.

Comparators (`comparators.py`): `canonical` (default, strict multiset equality
with field level diffs), `types` (type counts only), `subset` (reference must be
contained in candidate), `ignore`. Register your own:

```python
from difftest.comparators import register, Difference

@register("route_aggregator")
def route_aggregator(ref, cand, options):  # lists of normalised messages
    return []                               # list of Difference
```

and route to it in the scenario:
`{"name": "route_aggregator", "service": "RouteAggregator", "match": ["afrl.cmasi.Route*"]}`
with `"plugins": ["my_pkg.comparators"]` (or `--plugin`). Messages are claimed
by the first matching entry; the rest go to `canonical`.

## Golden files

When the Ada toolchain is unavailable, record once on a machine that has
`uxas_ada` (`--record-golden`), commit `golden/<name>.ada.golden.json`, and run
elsewhere with `--use-golden`. The golden stores raw hex plus the decoded
object and a fingerprint of the scenario's inputs; changing the messages,
services or settle values makes it stale (exit 3) until re-recorded.

## Tests

```
cd tests/cpp
python3 -m pytest -p no:cacheprovider difftest/tests      # or
python3 -m unittest discover -s difftest/tests -t .
```

## Known limitations

* Ada `uxas_ada` is assumed to accept the same `Bridge`/`Service` XML schema and
  `-cfgPath` switch as C++ (verified from `src/ada/src/main/uxas_ada.adb`);
  not exercised end-to-end here (no binaries/pyzmq in the authoring sandbox).
* If pylmcp/e3 cannot be imported, captures degrade to header + raw payload
  comparison.
* The scenario cannot yet inject messages from multiple concurrent sources or
  trigger external events other than ZeroMQ messages.
