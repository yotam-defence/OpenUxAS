// Unit tests for avtas::lmcp::ByteBuffer.
//
// Ported from src/ada/src/tests/test_bytebuffers.adb (put a Byte, String,
// UInt32, Unbounded_String, Real32, Boolean and UInt64 in order, rewind, read
// them back in the same order), plus byte-order, bounds and copy checks.
//
// Note: a default-constructed ByteBuffer has capacity 0 and silently ignores
// puts, so every fixture allocates storage first.

#include <gtest/gtest.h>

#include <cstdint>
#include <string>

#include "avtas/lmcp/ByteBuffer.h"

using avtas::lmcp::ByteBuffer;

class ByteBufferTest : public ::testing::Test {
protected:
    static constexpr uint32_t kCapacity = 1024;

    void SetUp() override { buffer.allocate(kCapacity); }

    ByteBuffer buffer;
};

// Mirrors Test_ByteBuffers (Ada): same values, same put/get order.
TEST_F(ByteBufferTest, AdaPortMixedRoundTrip)
{
    const uint8_t byteInput = 42;
    const std::string stringInput = "Hello World!";
    const uint32_t uint32Input = 42;
    const float real32Input = 42.42f;
    const bool boolInput = true;
    const uint64_t uint64Input = 84;

    buffer.putByte(byteInput);
    buffer.putString(stringInput);
    buffer.putUInt(uint32Input);
    buffer.putString(stringInput);  // Ada: Put_Unbounded_String
    buffer.putFloat(real32Input);
    buffer.putBool(boolInput);
    buffer.putULong(uint64Input);

    buffer.rewind();

    EXPECT_EQ(buffer.getByte(), byteInput);
    EXPECT_EQ(buffer.getString(), stringInput);
    EXPECT_EQ(buffer.getUInt(), uint32Input);
    EXPECT_EQ(buffer.getString(), stringInput);
    EXPECT_EQ(buffer.getFloat(), real32Input);
    EXPECT_EQ(buffer.getBool(), boolInput);
    EXPECT_EQ(buffer.getULong(), uint64Input);
}

TEST_F(ByteBufferTest, FreshBufferState)
{
    EXPECT_EQ(buffer.capacity(), kCapacity);
    EXPECT_EQ(buffer.position(), 0u);
    EXPECT_EQ(buffer.remaining(), kCapacity);
    EXPECT_TRUE(buffer.hasRemaining());
}

TEST(ByteBufferDefaultTest, DefaultConstructedHasNoStorage)
{
    ByteBuffer empty;
    EXPECT_EQ(empty.capacity(), 0u);
    EXPECT_FALSE(empty.hasRemaining());
    EXPECT_EQ(empty.getByteOrder(), ByteBuffer::ENDIAN_BIG);
    empty.putInt(7);  // ignored: no storage
    EXPECT_EQ(empty.position(), 0u);
}

TEST_F(ByteBufferTest, ScalarRoundTrips)
{
    buffer.putBool(false);
    buffer.putByte(0xFE);
    buffer.putShort(-1234);
    buffer.putUShort(65000);
    buffer.putInt(-123456789);
    buffer.putUInt(4000000000u);
    buffer.putLong(-1234567890123456789LL);
    buffer.putULong(18000000000000000000ULL);
    buffer.putFloat(-3.5f);
    buffer.putDouble(2.718281828459045);

    buffer.rewind();

    EXPECT_FALSE(buffer.getBool());
    EXPECT_EQ(buffer.getByte(), 0xFE);
    EXPECT_EQ(buffer.getShort(), -1234);
    EXPECT_EQ(buffer.getUShort(), 65000);
    EXPECT_EQ(buffer.getInt(), -123456789);
    EXPECT_EQ(buffer.getUInt(), 4000000000u);
    EXPECT_EQ(buffer.getLong(), -1234567890123456789LL);
    EXPECT_EQ(buffer.getULong(), 18000000000000000000ULL);
    EXPECT_EQ(buffer.getFloat(), -3.5f);
    EXPECT_EQ(buffer.getDouble(), 2.718281828459045);
}

TEST_F(ByteBufferTest, PositionAdvancesBySizeOfEachType)
{
    buffer.putByte(1);
    EXPECT_EQ(buffer.position(), 1u);
    buffer.putShort(1);
    EXPECT_EQ(buffer.position(), 3u);
    buffer.putInt(1);
    EXPECT_EQ(buffer.position(), 7u);
    buffer.putLong(1);
    EXPECT_EQ(buffer.position(), 15u);
    buffer.putFloat(1.f);
    EXPECT_EQ(buffer.position(), 19u);
    buffer.putDouble(1.0);
    EXPECT_EQ(buffer.position(), 27u);
    EXPECT_EQ(buffer.remaining(), kCapacity - 27u);
}

TEST_F(ByteBufferTest, DefaultByteOrderIsBigEndian)
{
    buffer.putUInt(0x01020304u);
    EXPECT_EQ(buffer.get(0u), 0x01);
    EXPECT_EQ(buffer.get(1u), 0x02);
    EXPECT_EQ(buffer.get(2u), 0x03);
    EXPECT_EQ(buffer.get(3u), 0x04);
}

TEST(ByteBufferOrderTest, LittleEndianLayoutAndRoundTrip)
{
    ByteBuffer le(ByteBuffer::ENDIAN_LITTLE);
    le.allocate(16);
    EXPECT_EQ(le.getByteOrder(), ByteBuffer::ENDIAN_LITTLE);
    le.putUInt(0x01020304u);
    le.putUShort(0xA1B2);
    EXPECT_EQ(le.get(0u), 0x04);
    EXPECT_EQ(le.get(1u), 0x03);
    EXPECT_EQ(le.get(2u), 0x02);
    EXPECT_EQ(le.get(3u), 0x01);
    EXPECT_EQ(le.get(4u), 0xB2);
    EXPECT_EQ(le.get(5u), 0xA1);
    le.rewind();
    EXPECT_EQ(le.getUInt(), 0x01020304u);
    EXPECT_EQ(le.getUShort(), 0xA1B2);
}

TEST_F(ByteBufferTest, StringIsLengthPrefixed)
{
    buffer.putString("abc");
    EXPECT_EQ(buffer.position(), 5u);  // 2-byte length + 3 chars
    EXPECT_EQ(buffer.get(0u), 0x00);
    EXPECT_EQ(buffer.get(1u), 0x03);
    EXPECT_EQ(buffer.get(2u), 'a');
    EXPECT_EQ(buffer.get(4u), 'c');
}

TEST_F(ByteBufferTest, EmptyStringRoundTrip)
{
    buffer.putString("");
    buffer.putInt(99);
    buffer.rewind();
    EXPECT_EQ(buffer.getString(), "");
    EXPECT_EQ(buffer.getInt(), 99);
}

TEST_F(ByteBufferTest, ArrayRoundTrips)
{
    const bool bools[3] = {true, false, true};
    const int16_t shorts[3] = {-1, 0, 32767};
    const int32_t ints[3] = {-100000, 0, 100000};
    const int64_t longs[2] = {-5000000000LL, 5000000000LL};
    const float floats[2] = {1.5f, -2.25f};
    const double doubles[2] = {1e100, -1e-100};

    buffer.putBoolArray(bools, 3);
    buffer.putShortArray(shorts, 3);
    buffer.putIntArray(ints, 3);
    buffer.putLongArray(longs, 2);
    buffer.putFloatArray(floats, 2);
    buffer.putDoubleArray(doubles, 2);
    buffer.rewind();

    bool outBools[3];
    int16_t outShorts[3];
    int32_t outInts[3];
    int64_t outLongs[2];
    float outFloats[2];
    double outDoubles[2];
    buffer.getBoolArray(outBools, 3);
    buffer.getShortArray(outShorts, 3);
    buffer.getIntArray(outInts, 3);
    buffer.getLongArray(outLongs, 2);
    buffer.getFloatArray(outFloats, 2);
    buffer.getDoubleArray(outDoubles, 2);

    for (int i = 0; i < 3; ++i) {
        EXPECT_EQ(outBools[i], bools[i]);
        EXPECT_EQ(outShorts[i], shorts[i]);
        EXPECT_EQ(outInts[i], ints[i]);
    }
    for (int i = 0; i < 2; ++i) {
        EXPECT_EQ(outLongs[i], longs[i]);
        EXPECT_EQ(outFloats[i], floats[i]);
        EXPECT_EQ(outDoubles[i], doubles[i]);
    }
}

TEST_F(ByteBufferTest, RawByteBlockPutGet)
{
    const uint8_t src[4] = {9, 8, 7, 6};
    buffer.put(src, 4);
    EXPECT_EQ(buffer.position(), 4u);
    buffer.rewind();
    uint8_t dst[4] = {0, 0, 0, 0};
    buffer.get(dst, 4);
    for (int i = 0; i < 4; ++i) {
        EXPECT_EQ(dst[i], src[i]);
    }
}

TEST_F(ByteBufferTest, ClearReleasesStorage)
{
    buffer.putInt(1);
    buffer.clear();
    EXPECT_EQ(buffer.capacity(), 0u);
    // liblmcp quirk: clear() frees storage, but position(0) on a zero-capacity
    // buffer is rejected, so the old position (4) is left in place.
    EXPECT_EQ(buffer.position(), 4u);
}

TEST_F(ByteBufferTest, RewindResetsPositionOnly)
{
    buffer.putInt(0x11223344);
    buffer.rewind();
    EXPECT_EQ(buffer.position(), 0u);
    EXPECT_EQ(buffer.capacity(), kCapacity);
    EXPECT_EQ(buffer.getInt(), 0x11223344);
}

TEST_F(ByteBufferTest, ReadPastEndReturnsZeroAndDoesNotAdvance)
{
    ByteBuffer small;
    small.allocate(2);
    small.putUShort(0xBEEF);
    small.rewind();
    EXPECT_EQ(small.getUInt(), 0u);  // only 2 bytes remain
    EXPECT_EQ(small.position(), 0u);
    EXPECT_EQ(small.getUShort(), 0xBEEF);
    EXPECT_FALSE(small.hasRemaining());
    EXPECT_EQ(small.getByte(), 0);
}

TEST_F(ByteBufferTest, WritePastEndIsIgnored)
{
    ByteBuffer small;
    small.allocate(3);
    small.putInt(0x01020304);  // needs 4 bytes: dropped
    EXPECT_EQ(small.position(), 0u);
    small.putShort(0x0506);
    EXPECT_EQ(small.position(), 2u);
}

TEST_F(ByteBufferTest, IndexedAccessDoesNotMovePosition)
{
    buffer.putByte(5);
    buffer.put(static_cast<uint32_t>(0), static_cast<uint8_t>(77));
    EXPECT_EQ(buffer.get(0u), 77);
    EXPECT_EQ(buffer.position(), 1u);
}

TEST_F(ByteBufferTest, CopyConstructorCopiesContentsAndOrder)
{
    buffer.putInt(1234);
    buffer.putString("copy");
    ByteBuffer copy(buffer);
    EXPECT_EQ(copy.capacity(), buffer.capacity());
    EXPECT_EQ(copy.getByteOrder(), buffer.getByteOrder());
    EXPECT_EQ(copy.position(), 0u);  // copies are rewound
    EXPECT_EQ(copy.getInt(), 1234);
    EXPECT_EQ(copy.getString(), "copy");
    EXPECT_NE(copy.array(), buffer.array());  // deep copy
}

TEST_F(ByteBufferTest, AssignmentCopiesContents)
{
    buffer.putLong(0x0102030405060708LL);
    ByteBuffer other;
    other = buffer;
    EXPECT_EQ(other.capacity(), buffer.capacity());
    EXPECT_EQ(other.getLong(), 0x0102030405060708LL);
}

TEST_F(ByteBufferTest, AllocateResizesAndRewinds)
{
    buffer.putInt(1);
    buffer.allocate(8);
    EXPECT_EQ(buffer.capacity(), 8u);
    EXPECT_EQ(buffer.position(), 0u);
}
