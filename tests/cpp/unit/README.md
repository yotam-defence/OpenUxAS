# C++ unit tests (GoogleTest)

Unit tests for the C++ code in `src/cpp` and for the `liblmcp` / generated
CMASI classes it depends on. These are fast, in-process tests: no ZeroMQ
sockets, no running UxAS instance. (End-to-end tests live in `tests/cpp/tests`
and `tests/cpp/run-tests`.)

## Layout and conventions

* Every test source is `tests/cpp/unit/test_<unit>.cpp`. The `test_` prefix is
  required: the Makefile picks files up with a `tests/cpp/unit/*.cpp` wildcard,
  so anything in this directory is compiled into the single unit-test binary.
* One fixture per unit under test: `class <Unit>Test : public ::testing::Test`
  in `test_<unit>.cpp`, with `TEST_F(<Unit>Test, <Behavior>)` cases. Use plain
  `TEST` only for cases that need no shared state.
* Test names describe behavior (`CorruptedPayloadFailsValidation`), not
  methods (`TestValidate`).
* Include project headers the way `src/cpp` does, e.g.
  `#include "avtas/lmcp/ByteBuffer.h"` and `#include "afrl/cmasi/Waypoint.h"`.
* Each test must be independent of order and of other test files. Do not rely
  on global state, the network, the filesystem or wall-clock time.
* `test_main.cpp` supplies `main()`; do not define another one.
* A default-constructed `avtas::lmcp::ByteBuffer` has capacity 0 and silently
  ignores writes; call `allocate(n)` first (the `ByteBufferTest` fixture does).
  `Factory::packMessage` returns a heap pointer owned by the caller and leaves
  the buffer positioned at its end: `rewind()` before `Factory::getObject`.

## Current suites

| File | Covers | Ported from |
| --- | --- | --- |
| `test_bytebuffer.cpp` | `ByteBuffer` put/get for all scalar, string and array types, endianness, bounds, copy semantics | `src/ada/src/tests/test_bytebuffers.adb` |
| `test_lmcp_factory.cpp` | `Factory` header layout, checksum, malformed input, `createObject`, pack/unpack round trips of `KeyValuePair`, `Location3D`, `Waypoint`, `AirVehicleState`, `MissionCommand`, `AutomationRequest`, `clone()` | `src/ada/src/tests/test_msg_decode.adb` (header checks) |

## Running

```
make test
```

builds `tests/cpp/unit/*.cpp` and runs the resulting binary (see the `test`
target in the top-level `Makefile`). Requirements: GoogleTest (headers plus
`libgtest`), and `liblmcp` plus the generated `afrl/cmasi` headers, i.e.
everything needed to build UxAS itself. Run a subset with a GoogleTest filter
on the binary, e.g. `--gtest_filter='ByteBufferTest.*'`.

## Adding a test

1. Create `tests/cpp/unit/test_<unit>.cpp`.
2. Include `<gtest/gtest.h>` and the headers under test.
3. Define a fixture and cases:

   ```cpp
   #include <gtest/gtest.h>
   #include "avtas/lmcp/ByteBuffer.h"

   class MyUnitTest : public ::testing::Test {
   protected:
       void SetUp() override { /* shared setup */ }
   };

   TEST_F(MyUnitTest, DoesTheExpectedThing) {
       EXPECT_EQ(1 + 1, 2);
   }
   ```
4. Run `make test`. No Makefile edit is needed because of the wildcard.

## Known gaps

* The Ada `Test_Msg_Decode` subscribes to a live ZeroMQ PUB socket at
  `tcp://127.0.0.1:5560`; that network loop is not ported. Its header
  decoding and validation steps are covered against locally packed messages.
  It compares the control string with the decimal `1634103916`, while the C++
  factory uses `0x4c4d4350` (`1280262992`); the C++ test asserts the latter.
* These tests were authored without a local `liblmcp`/GoogleTest build; the
  first `make test` run may surface API mismatches with the generated headers.
* Services under `src/cpp/Services` are not unit tested yet.
