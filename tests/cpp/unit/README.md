# C++ unit tests (GoogleTest)

Unit tests for the C++ code base (`src/cpp`) and the generated `liblmcp`.
They are built into a single binary, `obj/cpp/uxas_unit_tests`
(`$(OBJECT_DIR)/uxas_unit_tests`), separate from the `uxas` executable.

## Running

    make test          # build + run all tests in tests/cpp/unit/*.cpp
    make test-clean    # remove test objects and binary

Run a subset directly: `obj/cpp/uxas_unit_tests --gtest_filter='ByteBuffer*'`.

`make` picks up the anod build environment (include and library paths for
LMCP and the other dependencies) in the same way as `make all`, so run
`./anod build uxas` first (or `./anod build uxas-lmcp --qualifier=lang=cpp`
and the dependencies) on a fresh checkout.

## GoogleTest acquisition (decision)

GoogleTest comes from the **system package `libgtest-dev`** (Ubuntu 22.04 and
24.04 ship 1.11/1.14 with prebuilt `libgtest.a` and `libgtest_main.a`):

    sudo apt install libgtest-dev

The Makefile links `-lgtest -lgtest_main -llmcp -lpthread`. `infrastructure/install`
installs the package; CI installs it explicitly.

Fallback when the package is unavailable (older distributions that ship only
sources in `/usr/src/googletest`, or other OSes): build the libraries once and
point the Makefile at them.

    cmake -S /usr/src/googletest -B /tmp/gtest-build && cmake --build /tmp/gtest-build
    CPATH=/usr/src/googletest/googletest/include:$CPATH \
    make test GTEST_LIBS="-L/tmp/gtest-build/lib -lgtest -lgtest_main" GoogleTest is BSD-3-Clause.
Vendoring under `external_libraries/` was rejected to keep the tree small; an
anod spec was rejected because the package is available everywhere we build.

## Conventions

* One `test_<unit>.cpp` file per unit under test in this directory; every
  `*.cpp` here is compiled automatically (no list to maintain).
* Use `TEST(SuiteName, CaseName)`; suite names are `CamelCase` and start with
  the unit (`ByteBufferBounds`, `FlatEarthConversions`). Do not define
  `main()` - `gtest_main` provides it.
* Compile with the same flags as the product (`-std=c++17`); do not add
  test-only compiler flags to individual files.
* Tests must be deterministic and self-contained: no network, no wall-clock
  sleeps, no dependence on the working directory, no writes outside a
  temporary directory. Anything needing a running `uxas` belongs in the
  differential harness (`tests/cpp/difftest`) or the pylmcp functional tests
  (`tests/cpp/tests`), not here.
* Prefer `EXPECT_*` over `ASSERT_*` unless continuing would crash.
* Include project headers by their include-path name (`"avtas/lmcp/ByteBuffer.h"`,
  `"UxAS_StringUtil.h"`); the product `src/cpp` source directories are on the
  include path of the test build too (same `INCLUDES` as the product).
  Linking product objects into the tests is not wired yet: tests that need
  product `.cpp` code must extend `UNIT_TEST_BIN` prerequisites in the Makefile
  when first required.
* Tests for ported Ada behaviour should mirror the Ada test they replace and
  say so in the file header (see `test_bytebuffers.cpp`).

## Existing suites

| File | Covers |
|------|--------|
| `test_bytebuffers.cpp` | `avtas::lmcp::ByteBuffer` (liblmcp): primitive/string/array round trips, endianness, bounds and absolute access. Port of LmcpGen `test_bytebuffers.adb`. |
