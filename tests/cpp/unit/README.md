# C++ unit tests (GoogleTest)

Unit tests for the C++ code base live here. Every `*.cpp` file in this
directory is compiled into a single binary, `$(OBJECT_DIR)/unit_tests`
(default `obj/cpp/unit_tests`), which `make test` builds and runs.

- `main.cpp`: GoogleTest entry point.
- `test_bytebuffers.cpp`: port of `src/ada/src/tests/test_bytebuffers.adb`
  against `avtas::lmcp::ByteBuffer` from liblmcp.

To add a test, drop a new `test_<name>.cpp` file in this directory; no
Makefile change is needed.

## Running

    make test

Requires liblmcp (and its headers) to be reachable by the compiler, exactly
as for `make all`. When `anod` is present, the Makefile picks up the uxas
build environment automatically; `anod test uxas` does it explicitly.

## GoogleTest

By default the system GoogleTest is used (Debian/Ubuntu: `sudo apt-get install
libgtest-dev`; on 22.04 and 24.04 this package ships the compiled libraries).
The default link line is `-lgtest -lgtest_main -lpthread`.

To use another installation (e.g. built from source), override:

- `GTEST_DIR`: installation prefix; adds `-I$(GTEST_DIR)/include` and
  `-L$(GTEST_DIR)/lib`.
- `GTEST_LIBS`: complete replacement for the link libraries.

Example:

    make test GTEST_DIR=$HOME/opt/googletest GTEST_LIBS="-lgtest -lpthread"

Other variables: `CXX` (compiler, e.g. `make test CXX=clang++`), `OBJECT_DIR`.
