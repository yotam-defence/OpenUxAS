# difftest - Ada vs C++ differential replay harness

Runs the Ada reference (`uxas-ada`) and the C++ `uxas` with equivalent XML
configurations, replays the same ordered LMCP message sequence into each over
ZeroMQ (PublishPull bridge), captures every outbound LMCP message, canonicalises
and diffs. It is the parity gate for porting services from Ada to C++.

    cd tests/cpp   # or: PYTHONPATH=tests/cpp from the repo root
    python3 -m difftest run difftest/scenarios/smoke_heartbeat.json \
        --ada-golden --cpp-bin ../../obj/cpp/uxas

    make diff-smoke                        # the same, from the repo root
    python3 -m difftest compare ada.json cpp.json --scenario s.json
    python3 -m difftest canon capture.json
    python3 -m difftest list-comparators
    python3 -m pytest difftest/tests       # unit tests, no binaries needed

Exit codes: 0 match, 1 differences, 2 error (bad scenario, missing binary or
golden file, ...).

Live runs need `pyzmq` and the `pylmcp` dependencies (`e3-core`, available in
the anod venv). Everything else is plain standard library; PyYAML is optional
(scenarios may be `.yaml`).

## Binaries and golden files

* `--ada-bin/--cpp-bin`, else `UXAS_ADA_BIN`/`UXAS_CPP_BIN`, else
  `obj/ada/uxas-ada` / `obj/cpp/uxas`, else `PATH`. Both are launched as
  `<bin> -cfgPath <rendered cfg>` in a private temp directory.
* `--ada-golden` / `--cpp-golden` replay a cached capture instead of running
  that binary (when the Ada/Alire toolchain is unavailable).
* `--record-golden` stores the raw capture of each *live* run in
  `scenarios/golden/<scenario>.<ada|cpp>.json` (`--golden-dir` to change).
  Commit refreshed goldens together with the scenario change that required them.
* `scenarios/golden/smoke_heartbeat.ada.json` is **hand-authored** (the
  expectation is "no reaction to bridge-only heartbeats"); replace it with a
  real recording (`--record-golden`) once `uxas-ada` is built.
  Until then the smoke gate only verifies that the C++ binary starts, survives
  the heartbeat sequence and emits no reactions; it does **not** prove Ada parity
  (no Ada toolchain is available in the build sandbox).

## Scenario format (see `scenario.py` docstring)

JSON (or YAML): `name`, `entity_id`, `startup_settle_ms`, `config`
(XML template per binary, `${ENTITY_ID} ${PUB_ADDRESS} ${PULL_ADDRESS}
${RUN_DIR}` substituted), `messages` (ordered; `type` is an LMCP full or
suffix name, `fields` its attributes - nested objects as `{"_type": ...}` -,
`delay_ms` settle time after sending), `capture` (`window_ms` after the last
message, `include_descriptors`/`exclude_descriptors` globs), `canonical`,
`comparators`, `plugins`.

## Comparison strategy (design decision 1: option 1 + per-service hook)

1. **Canonicalisation** (`canon.py`): drop arrival times and source ids, strip
   `strip_fields` (default `Time`, `TimeStamp`) at any depth, renumber
   `remap_fields` (ids whose concrete value is irrelevant but whose
   cross-references matter) by first appearance, round floats, and sort by
   (descriptor, content) - over the whole capture, or inside fixed
   `sort_window_ms` buckets of arrival time. `keep_order_descriptors` opts
   individual descriptors out of sorting.
2. **Comparators** (`comparators.py`): per descriptor glob, chosen in the
   scenario. Built in: `exact` (multiset, default), `numeric`
   (`abs`/`rel` tolerance), `count`, `cpp_superset`, `ignore`. Services add
   their own:

       from difftest.comparators import register

       @register("assignment_cost_equal")
       def cmp(ada, cpp, params):      # canonical messages of one descriptor
           return []                   # list of difference strings

   Load with `"plugins": ["my_module"]` in the scenario or `--plugin my_module`.
3. Byte-for-byte comparison (option 3) is intentionally not offered.

## Layout

    difftest/{scenario,canon,comparators,report,golden,runner,cli}.py
    difftest/scenarios/<name>.json, scenarios/<name>/config.xml, scenarios/golden/
    difftest/tests/            pytest unit tests (no binaries)
