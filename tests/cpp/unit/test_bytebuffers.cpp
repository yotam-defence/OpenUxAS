// GoogleTest port of src/ada/src/tests/test_bytebuffers.adb, exercised against
// liblmcp's avtas::lmcp::ByteBuffer (the C++ reference implementation).
//
// Convention: do NOT define main() in tests under tests/cpp/unit; the binary is
// linked with -lgtest_main which supplies it (see tests/cpp/unit/README.md).

#include "avtas/lmcp/ByteBuffer.h"

#include <gtest/gtest.h>

#include <cstdint>
#include <string>

using avtas::lmcp::ByteBuffer;

namespace {

constexpr uint8_t kByteInput = 42;
const std::string kStringInput = "Hello World!";
constexpr uint32_t kUInt32Input = 42;
constexpr float kReal32Input = 42.42f;
constexpr bool kBoolInput = true;
constexpr uint64_t kUInt64Input = 84;

ByteBuffer makeBuffer(uint32_t capacity = 1024)
{
    ByteBuffer buffer;
    buffer.allocate(capacity);
    return buffer;
}

} // namespace

TEST(ByteBuffer, ByteRoundTrip)
{
    ByteBuffer buffer = makeBuffer();
    buffer.putByte(kByteInput);
    buffer.rewind();
    EXPECT_EQ(buffer.getByte(), kByteInput);
}

TEST(ByteBuffer, StringRoundTrip)
{
    ByteBuffer buffer = makeBuffer();
    buffer.putString(kStringInput);
    buffer.rewind();
    const std::string output = buffer.getString();
    EXPECT_EQ(output.size(), kStringInput.size());
    EXPECT_EQ(output, kStringInput);
}

TEST(ByteBuffer, UInt32RoundTrip)
{
    ByteBuffer buffer = makeBuffer();
    buffer.putUInt(kUInt32Input);
    buffer.rewind();
    EXPECT_EQ(buffer.getUInt(), kUInt32Input);
}

TEST(ByteBuffer, Real32RoundTrip)
{
    ByteBuffer buffer = makeBuffer();
    buffer.putFloat(kReal32Input);
    buffer.rewind();
    EXPECT_FLOAT_EQ(buffer.getFloat(), kReal32Input);
}

TEST(ByteBuffer, BoolRoundTrip)
{
    ByteBuffer buffer = makeBuffer();
    buffer.putBool(kBoolInput);
    buffer.putBool(!kBoolInput);
    buffer.rewind();
    EXPECT_EQ(buffer.getBool(), kBoolInput);
    EXPECT_EQ(buffer.getBool(), !kBoolInput);
}

TEST(ByteBuffer, UInt64RoundTrip)
{
    ByteBuffer buffer = makeBuffer();
    buffer.putULong(kUInt64Input);
    buffer.rewind();
    EXPECT_EQ(buffer.getULong(), kUInt64Input);
}

// Mirrors the Ada test: write every type in sequence, rewind, read back in the
// same order. Ordering of puts and gets must match.
TEST(ByteBuffer, SequentialMixedRoundTrip)
{
    ByteBuffer buffer = makeBuffer();
    buffer.putByte(kByteInput);
    buffer.putString(kStringInput);
    buffer.putUInt(kUInt32Input);
    buffer.putString(kStringInput); // Ada: Put_Unbounded_String
    buffer.putFloat(kReal32Input);
    buffer.putBool(kBoolInput);
    buffer.putULong(kUInt64Input);

    buffer.rewind();

    EXPECT_EQ(buffer.getByte(), kByteInput);
    EXPECT_EQ(buffer.getString(), kStringInput);
    EXPECT_EQ(buffer.getUInt(), kUInt32Input);
    EXPECT_EQ(buffer.getString(), kStringInput);
    EXPECT_FLOAT_EQ(buffer.getFloat(), kReal32Input);
    EXPECT_EQ(buffer.getBool(), kBoolInput);
    EXPECT_EQ(buffer.getULong(), kUInt64Input);
}

// LMCP wire format is big-endian by default.
TEST(ByteBuffer, UInt32IsBigEndianOnTheWire)
{
    ByteBuffer buffer = makeBuffer(16);
    buffer.putUInt(0x01020304u);
    ASSERT_EQ(buffer.position(), 4u);
    const uint8_t* raw = buffer.array();
    EXPECT_EQ(raw[0], 0x01);
    EXPECT_EQ(raw[1], 0x02);
    EXPECT_EQ(raw[2], 0x03);
    EXPECT_EQ(raw[3], 0x04);
}
