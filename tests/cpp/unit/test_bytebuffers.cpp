// Unit tests for avtas::lmcp::ByteBuffer (liblmcp).
//
// C++ port of src/ada/src/tests/test_bytebuffers.adb: values are written in
// a fixed order, the buffer is rewound, then read back in the same order.

#include "avtas/lmcp/ByteBuffer.h"

#include <gtest/gtest.h>

#include <cstdint>
#include <string>

using avtas::lmcp::ByteBuffer;

namespace
{
const uint8_t kByteInput = 42;
const std::string kStringInput = "Hello World!";
const uint32_t kUInt32Input = 42;
const float kReal32Input = 42.42f;
const bool kBooleanInput = true;
const uint64_t kUInt64Input = 84;
}

TEST(ByteBuffers, RoundTripMixedTypes)
{
    ByteBuffer buffer;
    buffer.allocate(1024);

    // NB: the order of the puts must match the order of the gets below
    buffer.putByte(kByteInput);
    buffer.putString(kStringInput);
    buffer.putUInt(kUInt32Input);
    buffer.putString(kStringInput);  // Ada "Unbounded_String" counterpart
    buffer.putFloat(kReal32Input);
    buffer.putBool(kBooleanInput);
    buffer.putULong(kUInt64Input);

    buffer.rewind();

    EXPECT_EQ(buffer.getByte(), kByteInput);
    EXPECT_EQ(buffer.getString(), kStringInput);
    EXPECT_EQ(buffer.getUInt(), kUInt32Input);
    EXPECT_EQ(buffer.getString(), kStringInput);
    EXPECT_EQ(buffer.getFloat(), kReal32Input);
    EXPECT_EQ(buffer.getBool(), kBooleanInput);
    EXPECT_EQ(buffer.getULong(), kUInt64Input);
}

TEST(ByteBuffers, AllocateSetsCapacityAndPosition)
{
    ByteBuffer buffer;
    buffer.allocate(16);
    EXPECT_EQ(buffer.capacity(), 16u);
    EXPECT_EQ(buffer.position(), 0u);
    EXPECT_EQ(buffer.remaining(), 16u);
    EXPECT_TRUE(buffer.hasRemaining());
}

TEST(ByteBuffers, PositionAdvancesAndRewinds)
{
    ByteBuffer buffer;
    buffer.allocate(16);
    buffer.putUInt(7);
    EXPECT_EQ(buffer.position(), 4u);
    buffer.rewind();
    EXPECT_EQ(buffer.position(), 0u);
}

TEST(ByteBuffers, BigEndianByDefault)
{
    ByteBuffer buffer;
    buffer.allocate(4);
    buffer.putUInt(0x01020304u);
    EXPECT_EQ(buffer.get(0), 0x01);
    EXPECT_EQ(buffer.get(3), 0x04);
}

TEST(ByteBuffers, LittleEndianWhenRequested)
{
    ByteBuffer buffer(ByteBuffer::ENDIAN_LITTLE);
    buffer.allocate(4);
    buffer.putUInt(0x01020304u);
    EXPECT_EQ(buffer.get(0), 0x04);
    EXPECT_EQ(buffer.get(3), 0x01);
    buffer.rewind();
    EXPECT_EQ(buffer.getUInt(), 0x01020304u);
}

TEST(ByteBuffers, EmptyStringRoundTrip)
{
    ByteBuffer buffer;
    buffer.allocate(8);
    buffer.putString("");
    buffer.rewind();
    EXPECT_EQ(buffer.getString(), "");
}
