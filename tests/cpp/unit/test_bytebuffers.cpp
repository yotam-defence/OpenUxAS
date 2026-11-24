// Port of src/ada/src/tests/test_bytebuffers.adb to GoogleTest, exercising
// the liblmcp C++ ByteBuffer (avtas/lmcp/ByteBuffer.h).
//
// NOTE: avtas/lmcp/ByteBuffer.h is provided by LmcpGen (template in
// LmcpGen/src/templates/cpp/ByteBuffer.h) and is installed with liblmcp; the
// generated tree src/cpp/LMCP is not checked in. These tests are written
// against that API (default capacity is 0, so allocate() must be called).
#include <gtest/gtest.h>

#include "avtas/lmcp/ByteBuffer.h"

#include <cstdint>
#include <string>

using avtas::lmcp::ByteBuffer;

namespace {
constexpr uint8_t kByte = 42;
const std::string kString = "Hello World!";
constexpr uint32_t kUInt32 = 42;
constexpr float kReal32 = 42.42f;
constexpr bool kBool = true;
constexpr uint64_t kUInt64 = 84;
}

// Mirrors the Ada test: put in order, rewind, get back in the same order.
TEST(ByteBuffer, MixedPutGetRoundTrip)
{
    ByteBuffer buffer;
    buffer.allocate(1024);

    buffer.putByte(kByte);
    buffer.putString(kString);
    buffer.putUInt(kUInt32);
    buffer.putString(kString);  // Ada: Put_Unbounded_String
    buffer.putFloat(kReal32);
    buffer.putBool(kBool);
    buffer.putULong(kUInt64);

    buffer.rewind();

    EXPECT_EQ(buffer.getByte(), kByte);
    EXPECT_EQ(buffer.getString(), kString);
    EXPECT_EQ(buffer.getUInt(), kUInt32);
    EXPECT_EQ(buffer.getString(), kString);
    EXPECT_EQ(buffer.getFloat(), kReal32);
    EXPECT_EQ(buffer.getBool(), kBool);
    EXPECT_EQ(buffer.getULong(), kUInt64);
}

TEST(ByteBuffer, IntegerTypes)
{
    ByteBuffer buffer;
    buffer.allocate(64);
    buffer.putShort(-1234).putUShort(65000).putInt(-123456789).putUInt(4000000000u)
          .putLong(-1234567890123LL).putULong(18000000000000000000ULL);
    buffer.rewind();
    EXPECT_EQ(buffer.getShort(), -1234);
    EXPECT_EQ(buffer.getUShort(), 65000);
    EXPECT_EQ(buffer.getInt(), -123456789);
    EXPECT_EQ(buffer.getUInt(), 4000000000u);
    EXPECT_EQ(buffer.getLong(), -1234567890123LL);
    EXPECT_EQ(buffer.getULong(), 18000000000000000000ULL);
}

TEST(ByteBuffer, FloatingPointTypes)
{
    ByteBuffer buffer;
    buffer.allocate(32);
    buffer.putFloat(3.5f).putDouble(-2.718281828459045);
    buffer.rewind();
    EXPECT_FLOAT_EQ(buffer.getFloat(), 3.5f);
    EXPECT_DOUBLE_EQ(buffer.getDouble(), -2.718281828459045);
}

TEST(ByteBuffer, EmptyString)
{
    ByteBuffer buffer;
    buffer.allocate(16);
    buffer.putString("");
    buffer.rewind();
    EXPECT_EQ(buffer.getString(), "");
}

TEST(ByteBuffer, Arrays)
{
    const int32_t in[3] = {1, -2, 3};
    int32_t out[3] = {0, 0, 0};
    ByteBuffer buffer;
    buffer.allocate(64);
    buffer.putIntArray(in, 3);
    buffer.rewind();
    buffer.getIntArray(out, 3);
    for (int i = 0; i < 3; ++i)
    {
        EXPECT_EQ(out[i], in[i]);
    }
}

TEST(ByteBuffer, BigEndianByteLayout)
{
    ByteBuffer buffer(ByteBuffer::ENDIAN_BIG);
    buffer.allocate(8);
    buffer.putUInt(0x01020304u);
    ASSERT_GE(buffer.capacity(), 4u);
    EXPECT_EQ(buffer.get(0u), 0x01);
    EXPECT_EQ(buffer.get(1u), 0x02);
    EXPECT_EQ(buffer.get(2u), 0x03);
    EXPECT_EQ(buffer.get(3u), 0x04);
}

TEST(ByteBuffer, LittleEndianByteLayout)
{
    ByteBuffer buffer(ByteBuffer::ENDIAN_LITTLE);
    buffer.allocate(8);
    buffer.putUInt(0x01020304u);
    EXPECT_EQ(buffer.get(0u), 0x04);
    EXPECT_EQ(buffer.get(3u), 0x01);
}

TEST(ByteBuffer, PositionAndRemaining)
{
    ByteBuffer buffer;
    buffer.allocate(16);
    EXPECT_EQ(buffer.capacity(), 16u);
    EXPECT_EQ(buffer.position(), 0u);
    buffer.putUInt(7);
    EXPECT_EQ(buffer.position(), 4u);
    EXPECT_EQ(buffer.remaining(), 12u);
    EXPECT_TRUE(buffer.hasRemaining());
    buffer.rewind();
    EXPECT_EQ(buffer.position(), 0u);
}

TEST(ByteBuffer, CopyIsIndependent)
{
    ByteBuffer a;
    a.allocate(16);
    a.putUInt(99);
    ByteBuffer b(a);
    b.rewind();
    EXPECT_EQ(b.getUInt(), 99u);
}
