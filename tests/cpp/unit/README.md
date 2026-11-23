# C++ unit tests (GoogleTest)

Unit tests for the OpenUxAS C++ code base and for the liblmcp APIs it relies on.
They are independent from the pylmcp based functional testsuite in `tests/cpp`.

## Running

    make test

builds `tests/cpp/unit/test_*.cpp` into a single binary,
`$(OBJECT_DIR)/unit_tests` (default `obj/cpp/unit_tests`), and runs it.
Objects go to `$(OBJECT_DIR)/unit/`. `make clean` removes them.

Useful variables:

- `UNIT_TEST_ARGS="--gtest_filter=ByteBufferTest.*"` passes arguments to the binary.
- `CXX_BIN=clang++` selects the compiler (C++17, GCC 11+ / Clang 14+).
- `GTEST_SRC_DIR=/path/to/googletest/googletest` selects the GoogleTest sources used by the fallback.
- `UNIT_TEST_EXTRA_CXX_FLAGS="-I... -L..."` adds include/library paths (e.g. for liblmcp when not using anod).

Tests link only against `liblmcp` (and GoogleTest), never against the `uxas`
sources, so they build quickly. liblmcp headers/libraries come from the anod
build environment (the top level Makefile imports it automatically) or from
the system paths.

## GoogleTest acquisition (design decision)

GoogleTest is BSD-3-Clause. We do not vendor it and do not add an anod spec:

1. **System package (preferred)**: `sudo apt-get install libgtest-dev`
   (Ubuntu 22.04/24.04 ship `libgtest.a` and `libgtest_main.a`). The Makefile
   probes whether `-lgtest` links and uses it.
2. **Fallback**: if no usable system library is found, the Makefile compiles
   `src/gtest-all.cc` and `src/gtest_main.cc` directly from `GTEST_SRC_DIR`
   (default `/usr/src/googletest/googletest`, also installed by `libgtest-dev`
   and `googletest`). No CMake step is needed.

CI installs `libgtest-dev` and runs `make test`.

## Adding tests

Create `tests/cpp/unit/test_<name>.cpp` using `#include <gtest/gtest.h>`; it is
picked up automatically. No `main()` is needed (`gtest_main` is linked).

## Current suites

- `test_bytebuffers.cpp`: port of `src/ada/src/tests/test_bytebuffers.adb`
  against `avtas::lmcp::ByteBuffer`, plus big-endian wire layout and bounds checks.
