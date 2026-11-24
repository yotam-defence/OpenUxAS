// C++ port of src/ada/src/tests/test_bytebuffers.adb, exercising
// avtas::lmcp::ByteBuffer from liblmcp.

#include <cstdint>
#include <string>

#include <gtest/gtest.h>

#include "avtas/lmcp/ByteBuffer.h"

using avtas::lmcp::ByteBuffer;

namespace {

const uint8_t     kByteInput    = 42;
const std::string kStringInput  = "Hello World!";
const uint32_t    kUInt32Input  = 42;
const float       kReal32Input  = 42.42f;
const bool        kBooleanInput = true;
const uint64_t    kUInt64Input  = 84;

// Same capacity as the Ada test
const uint32_t kCapacity = 1024;

}  // namespace

// Mirrors the Ada test: put values of several types, rewind, and read them
// back in the same order.
TEST(ByteBuffers, PutThenGetRoundTrip)
{
    ByteBuffer buffer;
    buffer.allocate(kCapacity);
    ASSERT_EQ(kCapacity, buffer.capacity());

    // NB: the order of the puts must match the order of the gets below
    buffer.putByte(kByteInput);
    buffer.putString(kStringInput);
    buffer.putUInt(kUInt32Input);
    buffer.putString(kStringInput);  // Ada "Unbounded_String" counterpart
    buffer.putFloat(kReal32Input);
    buffer.putBool(kBooleanInput);
    buffer.putULong(kUInt64Input);

    buffer.rewind();
    EXPECT_EQ(0u, buffer.position());

    EXPECT_EQ(kByteInput, buffer.getByte());

    const std::string str = buffer.getString();
    EXPECT_EQ(kStringInput.size(), str.size());
    EXPECT_EQ(kStringInput, str);

    EXPECT_EQ(kUInt32Input, buffer.getUInt());

    EXPECT_EQ(kStringInput, buffer.getString());

    EXPECT_EQ(kReal32Input, buffer.getFloat());
    EXPECT_EQ(kBooleanInput, buffer.getBool());
    EXPECT_EQ(kUInt64Input, buffer.getULong());
}

TEST(ByteBuffers, PositionAdvancesByTypeSize)
{
    ByteBuffer buffer;
    buffer.allocate(kCapacity);

    EXPECT_EQ(0u, buffer.position());
    buffer.putByte(kByteInput);
    EXPECT_EQ(1u, buffer.position());
    buffer.putUInt(kUInt32Input);
    EXPECT_EQ(5u, buffer.position());
    buffer.putULong(kUInt64Input);
    EXPECT_EQ(13u, buffer.position());
    buffer.putFloat(kReal32Input);
    EXPECT_EQ(17u, buffer.position());
    EXPECT_EQ(kCapacity - 17u, buffer.remaining());
    EXPECT_TRUE(buffer.hasRemaining());

    buffer.rewind();
    EXPECT_EQ(0u, buffer.position());
    EXPECT_EQ(kCapacity, buffer.remaining());
}

TEST(ByteBuffers, BooleanBothValues)
{
    ByteBuffer buffer;
    buffer.allocate(kCapacity);
    buffer.putBool(true);
    buffer.putBool(false);
    buffer.rewind();
    EXPECT_TRUE(buffer.getBool());
    EXPECT_FALSE(buffer.getBool());
}

TEST(ByteBuffers, EmptyString)
{
    ByteBuffer buffer;
    buffer.allocate(kCapacity);
    buffer.putString("");
    buffer.putByte(kByteInput);
    buffer.rewind();
    EXPECT_EQ("", buffer.getString());
    EXPECT_EQ(kByteInput, buffer.getByte());
}

TEST(ByteBuffers, BigEndianByDefault)
{
    ByteBuffer buffer;
    EXPECT_EQ(ByteBuffer::ENDIAN_BIG, buffer.getByteOrder());
    buffer.allocate(8);
    buffer.putUInt(0x01020304u);
    const uint8_t* raw = buffer.array();
    EXPECT_EQ(0x01, raw[0]);
    EXPECT_EQ(0x02, raw[1]);
    EXPECT_EQ(0x03, raw[2]);
    EXPECT_EQ(0x04, raw[3]);
}

TEST(ByteBuffers, LittleEndianOrder)
{
    ByteBuffer buffer(ByteBuffer::ENDIAN_LITTLE);
    EXPECT_EQ(ByteBuffer::ENDIAN_LITTLE, buffer.getByteOrder());
    buffer.allocate(8);
    buffer.putUInt(0x01020304u);
    const uint8_t* raw = buffer.array();
    EXPECT_EQ(0x04, raw[0]);
    EXPECT_EQ(0x03, raw[1]);
    EXPECT_EQ(0x02, raw[2]);
    EXPECT_EQ(0x01, raw[3]);
    buffer.rewind();
    EXPECT_EQ(0x01020304u, buffer.getUInt());
}

TEST(ByteBuffers, AbsoluteGetPut)
{
    ByteBuffer buffer;
    buffer.allocate(16);
    buffer.put(static_cast<uint32_t>(3), static_cast<uint8_t>(0xAB));
    EXPECT_EQ(0xAB, buffer.get(static_cast<uint32_t>(3)));
}

TEST(ByteBuffers, CopyPreservesContents)
{
    ByteBuffer buffer;
    buffer.allocate(kCapacity);
    buffer.putUInt(kUInt32Input);
    buffer.putULong(kUInt64Input);

    ByteBuffer copy(buffer);
    EXPECT_EQ(buffer.capacity(), copy.capacity());
    copy.rewind();
    EXPECT_EQ(kUInt32Input, copy.getUInt());
    EXPECT_EQ(kUInt64Input, copy.getULong());
}
