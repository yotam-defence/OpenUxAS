// Port of src/ada/src/tests/test_bytebuffers.adb to GoogleTest, exercising
// liblmcp's avtas::lmcp::ByteBuffer (the C++ counterpart of the Ada
// AVTAS.LMCP.ByteBuffers package). Additional tests check the big-endian wire
// layout and buffer bounds behaviour.

#include "avtas/lmcp/ByteBuffer.h"

#include <gtest/gtest.h>

#include <cstdint>
#include <cstring>
#include <string>

using avtas::lmcp::ByteBuffer;

namespace {

const uint8_t kByteInput = 42;
const char* const kStringInput = "Hello World!";
const uint32_t kUInt32Input = 42;
const float kReal32Input = 42.42f;
const bool kBoolInput = true;
const uint64_t kUInt64Input = 84;

class ByteBufferTest : public ::testing::Test {
protected:
    void SetUp() override { buffer.allocate(1024); }
    ByteBuffer buffer;  // big endian by default
};

}  // namespace

// Direct port of the Ada Test_ByteBuffers procedure: the order of the puts
// must match the order of the gets.
TEST_F(ByteBufferTest, RoundTripMixedValues) {
    buffer.putByte(kByteInput);
    buffer.putString(kStringInput);
    buffer.putUInt(kUInt32Input);
    buffer.putString(kStringInput);  // Ada: Put_Unbounded_String
    buffer.putFloat(kReal32Input);
    buffer.putBool(kBoolInput);
    buffer.putULong(kUInt64Input);

    buffer.rewind();

    EXPECT_EQ(buffer.getByte(), kByteInput);
    EXPECT_EQ(buffer.getString(), std::string(kStringInput));
    EXPECT_EQ(buffer.getUInt(), kUInt32Input);
    EXPECT_EQ(buffer.getString(), std::string(kStringInput));
    EXPECT_FLOAT_EQ(buffer.getFloat(), kReal32Input);
    EXPECT_EQ(buffer.getBool(), kBoolInput);
    EXPECT_EQ(buffer.getULong(), kUInt64Input);
}

TEST_F(ByteBufferTest, DefaultByteOrderIsBigEndian) {
    EXPECT_EQ(buffer.getByteOrder(), ByteBuffer::ENDIAN_BIG);
    ByteBuffer little(ByteBuffer::ENDIAN_LITTLE);
    EXPECT_EQ(little.getByteOrder(), ByteBuffer::ENDIAN_LITTLE);
}

TEST_F(ByteBufferTest, AllocateSetsCapacityAndPosition) {
    EXPECT_EQ(buffer.capacity(), 1024u);
    EXPECT_EQ(buffer.position(), 0u);
    EXPECT_EQ(buffer.remaining(), 1024u);
    EXPECT_TRUE(buffer.hasRemaining());
}

TEST_F(ByteBufferTest, PutGetByte) {
    buffer.putByte(kByteInput);
    EXPECT_EQ(buffer.position(), 1u);
    buffer.rewind();
    EXPECT_EQ(buffer.position(), 0u);
    EXPECT_EQ(buffer.getByte(), kByteInput);
    EXPECT_EQ(buffer.position(), 1u);
}

TEST_F(ByteBufferTest, PutGetByteViaPutGet) {
    buffer.put(static_cast<uint8_t>(0xAB));
    buffer.rewind();
    EXPECT_EQ(buffer.get(), 0xAB);
}

TEST_F(ByteBufferTest, PutGetString) {
    buffer.putString(kStringInput);
    // 2-byte length prefix followed by the characters
    EXPECT_EQ(buffer.position(), 2u + std::strlen(kStringInput));
    buffer.rewind();
    EXPECT_EQ(buffer.getString(), std::string(kStringInput));
}

TEST_F(ByteBufferTest, PutGetEmptyString) {
    buffer.putString("");
    EXPECT_EQ(buffer.position(), 2u);
    buffer.rewind();
    EXPECT_EQ(buffer.getString(), "");
}

TEST_F(ByteBufferTest, StringLayoutIsBigEndianLengthPrefixed) {
    buffer.putString("abc");
    const uint8_t* raw = buffer.array();
    EXPECT_EQ(raw[0], 0x00);
    EXPECT_EQ(raw[1], 0x03);
    EXPECT_EQ(raw[2], 'a');
    EXPECT_EQ(raw[3], 'b');
    EXPECT_EQ(raw[4], 'c');
}

TEST_F(ByteBufferTest, PutGetUInt32) {
    buffer.putUInt(kUInt32Input);
    EXPECT_EQ(buffer.position(), 4u);
    buffer.rewind();
    EXPECT_EQ(buffer.getUInt(), kUInt32Input);
}

TEST_F(ByteBufferTest, UInt32LayoutIsBigEndian) {
    buffer.putUInt(0x01020304u);
    const uint8_t* raw = buffer.array();
    EXPECT_EQ(raw[0], 0x01);
    EXPECT_EQ(raw[1], 0x02);
    EXPECT_EQ(raw[2], 0x03);
    EXPECT_EQ(raw[3], 0x04);
}

TEST_F(ByteBufferTest, PutGetInt32Negative) {
    buffer.putInt(-2);
    buffer.rewind();
    EXPECT_EQ(buffer.getInt(), -2);
    const uint8_t* raw = buffer.array();
    EXPECT_EQ(raw[0], 0xFF);
    EXPECT_EQ(raw[3], 0xFE);
}

TEST_F(ByteBufferTest, PutGetReal32) {
    buffer.putFloat(kReal32Input);
    EXPECT_EQ(buffer.position(), 4u);
    buffer.rewind();
    EXPECT_EQ(buffer.getFloat(), kReal32Input);
}

TEST_F(ByteBufferTest, Real32LayoutIsBigEndianIeee754) {
    buffer.putFloat(kReal32Input);  // 42.42f == 0x4229AE14
    const uint8_t* raw = buffer.array();
    EXPECT_EQ(raw[0], 0x42);
    EXPECT_EQ(raw[1], 0x29);
    EXPECT_EQ(raw[2], 0xAE);
    EXPECT_EQ(raw[3], 0x14);
}

TEST_F(ByteBufferTest, PutGetBool) {
    buffer.putBool(true);
    buffer.putBool(false);
    EXPECT_EQ(buffer.position(), 2u);
    buffer.rewind();
    EXPECT_TRUE(buffer.getBool());
    EXPECT_FALSE(buffer.getBool());
}

TEST_F(ByteBufferTest, PutGetUInt64) {
    buffer.putULong(kUInt64Input);
    EXPECT_EQ(buffer.position(), 8u);
    buffer.rewind();
    EXPECT_EQ(buffer.getULong(), kUInt64Input);
}

TEST_F(ByteBufferTest, UInt64LayoutIsBigEndian) {
    buffer.putULong(0x0102030405060708ULL);
    const uint8_t* raw = buffer.array();
    for (int i = 0; i < 8; ++i) {
        EXPECT_EQ(raw[i], i + 1) << "byte " << i;
    }
    buffer.rewind();
    EXPECT_EQ(buffer.getULong(), 0x0102030405060708ULL);
}

TEST_F(ByteBufferTest, PutGetShortAndDouble) {
    buffer.putShort(-1234);
    buffer.putUShort(54321);
    buffer.putDouble(3.141592653589793);
    buffer.putLong(-5000000000LL);
    buffer.rewind();
    EXPECT_EQ(buffer.getShort(), -1234);
    EXPECT_EQ(buffer.getUShort(), 54321);
    EXPECT_DOUBLE_EQ(buffer.getDouble(), 3.141592653589793);
    EXPECT_EQ(buffer.getLong(), -5000000000LL);
}

TEST_F(ByteBufferTest, LittleEndianLayout) {
    ByteBuffer little(ByteBuffer::ENDIAN_LITTLE);
    little.allocate(16);
    little.putUInt(0x01020304u);
    const uint8_t* raw = little.array();
    // Wire data is always big endian in LMCP unless the buffer is configured
    // otherwise; this documents the actual behaviour of the liblmcp version.
    const bool hostIsLittle = [] {
        const uint16_t v = 1;
        uint8_t b;
        std::memcpy(&b, &v, 1);
        return b == 1;
    }();
    if (hostIsLittle) {
        EXPECT_EQ(raw[0], 0x04);
        EXPECT_EQ(raw[3], 0x01);
    }
    little.rewind();
    EXPECT_EQ(little.getUInt(), 0x01020304u);
}

TEST_F(ByteBufferTest, ArrayPutGet) {
    const uint8_t in[5] = {1, 2, 3, 4, 5};
    buffer.putByteArray(in, 5);
    EXPECT_EQ(buffer.position(), 5u);
    buffer.rewind();
    uint8_t out[5] = {0};
    buffer.getByteArray(out, 5);
    EXPECT_EQ(0, std::memcmp(in, out, 5));
}

TEST_F(ByteBufferTest, RewindResetsPositionOnly) {
    buffer.putUInt(7);
    buffer.putUInt(9);
    buffer.rewind();
    EXPECT_EQ(buffer.position(), 0u);
    EXPECT_EQ(buffer.capacity(), 1024u);
    EXPECT_EQ(buffer.getUInt(), 7u);
    EXPECT_EQ(buffer.getUInt(), 9u);
}

TEST_F(ByteBufferTest, PutBeyondCapacityIsIgnored) {
    ByteBuffer small;
    small.allocate(3);
    small.putUInt(0xDEADBEEFu);  // needs 4 bytes, only 3 available
    EXPECT_EQ(small.position(), 0u);
    small.putByte(1).putByte(2).putByte(3);
    EXPECT_EQ(small.position(), 3u);
    EXPECT_FALSE(small.hasRemaining());
}

TEST_F(ByteBufferTest, CopyConstructorCopiesContents) {
    buffer.putUInt(0xCAFEBABEu);
    ByteBuffer copy(buffer);
    EXPECT_EQ(copy.capacity(), buffer.capacity());
    EXPECT_EQ(copy.position(), 0u);
    EXPECT_EQ(copy.getUInt(), 0xCAFEBABEu);
}

TEST_F(ByteBufferTest, ClearReleasesStorage) {
    buffer.putByte(1);
    buffer.clear();
    // Note: liblmcp's position() ignores values >= capacity(), so after
    // clear() the position is not asserted here.
    EXPECT_EQ(buffer.capacity(), 0u);
    EXPECT_EQ(buffer.array(), nullptr);
}
