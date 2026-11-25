# C++ unit tests (GoogleTest)

Fast, service-free unit tests for the C++ code base. They are separate from the
integration tests driven by `tests/cpp/run-tests`.

## Running

    make test            # build obj/cpp/unit_tests and run it
    make unit-tests      # build only

Under anod: `./anod test uxas` (runs `make test`).

GoogleTest is expected as a system package (`apt install libgtest-dev`; on
Ubuntu 22.04/24.04 it provides `libgtest.a` and `libgtest_main.a`). Overrides:

    make test GTEST_DIR=/opt/gtest              # adds -I$GTEST_DIR/include -L$GTEST_DIR/lib
    make test GTEST_LIBS="-L/x/lib -lgtest -lgtest_main"

liblmcp (`avtas::lmcp::ByteBuffer`, generated into `src/cpp/LMCP` / provided by
the `uxas-lmcp` anod dependency) must be available, as for `make all`.

## Conventions

- One file per unit under test: `tests/cpp/unit/test_<unit>.cpp`
  (e.g. `test_bytebuffers.cpp`, `test_stringutil.cpp`). Every `*.cpp` in this
  directory is picked up automatically; no Makefile edit is needed.
- Use `TEST(Suite, Name)` with `Suite` = CamelCase unit name and `Name`
  describing the behaviour (`SplitKeepsTrailingEmptyToken`).
- No `main`: the Makefile links `gtest_main`. Only provide your own `main` in
  a file named `main.cpp` if custom global setup is needed (then drop
  `-lgtest_main` via GTEST_LIBS).
- Tests must not need network, ZeroMQ sockets, files outside a temp dir, or
  running services. Header-only utilities from `src/cpp/Utilities` can be
  included directly (that directory is on the include path); for utilities with
  a `.cpp`, add it to `UNIT_TEST_EXTRA_SOURCES` in the Makefile.
- Ports of Ada tests (`src/ada/src/tests`) should mirror the original check
  order and cite the source file in a header comment.

## Adding tests in later milestones

1. Add `test_<unit>.cpp` here (GoogleTest, conventions above).
2. If it needs a non-header source, append it to `UNIT_TEST_EXTRA_SOURCES`
   in the Makefile; if it needs extra libs, append to `UNIT_TEST_LIBS`.
3. Run `make test`; CI (`.github/workflows/uxas-cpp.yaml`) runs the same
   target with both GCC and Clang.
