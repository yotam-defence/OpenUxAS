# C++ unit tests (GoogleTest)

Sources in this directory (`*.cpp`) are compiled into a single binary by the
top-level Makefile:

    make test                       # build and run all unit tests
    make test UNIT_TEST_FILTER='ByteBuffer.*'
    make test GTEST_INCLUDE_DIR=/opt/gtest/include GTEST_LIB_DIR=/opt/gtest/lib

The binary is `$(OBJECT_DIR)/unit_tests/uxas_unit_tests` (default
`obj/cpp/unit_tests/`). `make clean` removes it. Link flags are
`-lgtest -lgtest_main -llmcp -lpthread`.

## Dependency decision: GoogleTest

GoogleTest (BSD-3-Clause) is taken from the system package `libgtest-dev`
(Ubuntu 22.04/24.04 ship the static libs `libgtest.a`/`libgtest_main.a`), and
CI installs it with apt. Alternatives considered: building it from source in a
new anod spec, or vendoring under `external_libraries/`; both were rejected to
keep the build simple. Override `GTEST_INCLUDE_DIR`/`GTEST_LIB_DIR` to use
another installation.

## Suites

- `test_smoke.cpp`: no liblmcp required; checks C++17 and GoogleTest wiring.
- `test_bytebuffers.cpp`: port of `src/ada/src/tests/test_bytebuffers.adb`
  against liblmcp `avtas::lmcp::ByteBuffer`. liblmcp and its headers
  (`avtas/lmcp/ByteBuffer.h`) come from LmcpGen (template:
  `LmcpGen/src/templates/cpp/ByteBuffer.h`); the generated `src/cpp/LMCP`
  tree is not checked in, so the include/library paths must point at the
  generated/installed liblmcp (anod does this via `uxas-lmcp`).

Add new tests as `tests/cpp/unit/test_<name>.cpp`; they are picked up by wildcard.
