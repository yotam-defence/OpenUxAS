# C++ unit tests (GoogleTest)

Unit tests for the C++ code base and for the liblmcp APIs it relies on.
Every `tests/cpp/unit/*.cpp` file is compiled into one binary,
`$(OBJECT_DIR)/unit_tests` (default `obj/cpp/unit_tests`).

## Running

    make test                     # build + run (GCC >= 11 or Clang >= 14, C++17)
    make test OBJECT_DIR=/tmp/obj # choose another output directory

The link line is `-lgtest -lgtest_main -llmcp -lpthread`. liblmcp comes from
the anod environment (`./anod build uxas-lmcp --qualifier=lang=cpp`); the
Makefile picks it up automatically through `anod printenv` unless
`SKIP_ANOD_SETUP=true`.

## Decision: how GoogleTest is acquired

Options considered:

1. A new anod spec building googletest from source.
2. The system package (`libgtest-dev`), installed in CI. **Chosen.**
3. Vendoring googletest under `external_libraries/`.

Rationale: GoogleTest (BSD-3-Clause) is only needed to build tests, never by
the shipped `uxas` binary, so it does not belong in the anod dependency graph
that produces release artefacts. On Ubuntu 22.04 and 24.04 `libgtest-dev`
ships sources plus (since 1.11/1.12) prebuilt `libgtest.a`/`libgtest_main.a`,
so no extra step is needed; a source build avoids ABI mismatches but adds
build time and another spec to maintain; vendoring adds third-party code to
the repository. Install with `sudo apt-get install libgtest-dev`
(on older images `cmake` + build in `/usr/src/googletest` may be required).
If we later need a pinned version, option 1 can be added without changing the
test sources, only the Makefile link flags.

## Conventions

* One `test_<topic>.cpp` per unit under test; add the file and `make test`
  picks it up (no Makefile edit).
* Do not define `main()`: `-lgtest_main` supplies it. A test needing custom
  setup must be a separate binary.
* Use `TEST(Suite, Name)`; suite name is the class/area under test.
* Tests must be hermetic (no ZeroMQ sockets, network, or files outside a temp
  dir); end-to-end behaviour belongs in `tests/cpp/differential` or the
  pylmcp-based testsuite.
* Code must compile warning-free with `ENABLE_WARNINGS=true` (`-Wall`).

## Current suites

* `test_bytebuffers.cpp` - port of `src/ada/src/tests/test_bytebuffers.adb`
  (byte, string, uint32, real32, bool, uint64 round trips) plus a big-endian
  wire check, against `avtas::lmcp::ByteBuffer`.
