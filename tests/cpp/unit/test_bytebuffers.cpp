// GoogleTest port of src/ada/src/tests/test_bytebuffers.adb, exercising the
// C++ avtas::lmcp::ByteBuffer shipped in liblmcp.

#include <gtest/gtest.h>

#include <cstdint>
#include <cstring>
#include <string>

#include "avtas/lmcp/ByteBuffer.h"

using avtas::lmcp::ByteBuffer;

namespace {

ByteBuffer makeBuffer(uint32_t size, ByteBuffer::ByteOrder order = ByteBuffer::ENDIAN_BIG)
{
    ByteBuffer buf(order);
    buf.allocate(size);
    return buf;
}

} // namespace

TEST(ByteBufferBasics, DefaultIsEmptyBigEndian)
{
    ByteBuffer buf;
    EXPECT_EQ(0u, buf.capacity());
    EXPECT_EQ(0u, buf.position());
    EXPECT_EQ(0u, buf.remaining());
    EXPECT_FALSE(buf.hasRemaining());
    EXPECT_EQ(ByteBuffer::ENDIAN_BIG, buf.getByteOrder());
}

TEST(ByteBufferBasics, AllocateSetsCapacityAndRemaining)
{
    ByteBuffer buf;
    buf.allocate(16);
    EXPECT_EQ(16u, buf.capacity());
    EXPECT_EQ(0u, buf.position());
    EXPECT_EQ(16u, buf.remaining());
    EXPECT_TRUE(buf.hasRemaining());
    EXPECT_NE(nullptr, buf.array());
}

TEST(ByteBufferBasics, ClearReleasesStorage)
{
    ByteBuffer buf = makeBuffer(8);
    buf.putInt(1);
    buf.clear();
    EXPECT_EQ(0u, buf.capacity());
    // Note: position is intentionally not checked here. clear() calls
    // position(0) on a zero-capacity buffer, which position() rejects, so the
    // stale position survives (known liblmcp quirk).
    EXPECT_EQ(nullptr, buf.array());
}

TEST(ByteBufferPosition, PositionAndRewind)
{
    ByteBuffer buf = makeBuffer(16);
    buf.putInt(7);
    EXPECT_EQ(4u, buf.position());
    EXPECT_EQ(12u, buf.remaining());
    buf.position(10);
    EXPECT_EQ(10u, buf.position());
    buf.rewind();
    EXPECT_EQ(0u, buf.position());
    EXPECT_EQ(16u, buf.remaining());
}

TEST(ByteBufferPosition, PositionBeyondCapacityIsIgnored)
{
    ByteBuffer buf = makeBuffer(8);
    buf.position(3);
    buf.position(8);   // == capacity, rejected
    EXPECT_EQ(3u, buf.position());
    buf.position(100); // > capacity, rejected
    EXPECT_EQ(3u, buf.position());
}

TEST(ByteBufferPutGet, Byte)
{
    ByteBuffer buf = makeBuffer(4);
    buf.putByte(42);
    buf.rewind();
    EXPECT_EQ(42, buf.getByte());
    EXPECT_EQ(1u, buf.position());
}

TEST(ByteBufferPutGet, RelativeGetPutSingleByte)
{
    ByteBuffer buf = makeBuffer(2);
    buf.put(static_cast<uint8_t>(0xAB)).put(static_cast<uint8_t>(0xCD));
    buf.rewind();
    EXPECT_EQ(0xAB, buf.get());
    EXPECT_EQ(0xCD, buf.get());
    EXPECT_FALSE(buf.hasRemaining());
}

TEST(ByteBufferPutGet, AbsoluteGetPutDoNotMovePosition)
{
    ByteBuffer buf = makeBuffer(4);
    buf.put(2, static_cast<uint8_t>(0x5A));
    EXPECT_EQ(0u, buf.position());
    EXPECT_EQ(0x5A, buf.get(static_cast<uint32_t>(2)));
    EXPECT_EQ(0u, buf.get(static_cast<uint32_t>(4))); // out of range reads 0
}

TEST(ByteBufferPutGet, Bool)
{
    ByteBuffer buf = makeBuffer(2);
    buf.putBool(true).putBool(false);
    buf.rewind();
    EXPECT_TRUE(buf.getBool());
    EXPECT_FALSE(buf.getBool());
}

TEST(ByteBufferPutGet, Short)
{
    ByteBuffer buf = makeBuffer(4);
    buf.putShort(-1234).putUShort(65000);
    buf.rewind();
    EXPECT_EQ(-1234, buf.getShort());
    EXPECT_EQ(65000, buf.getUShort());
}

TEST(ByteBufferPutGet, Int)
{
    ByteBuffer buf = makeBuffer(8);
    buf.putInt(-123456789).putUInt(4000000000u);
    buf.rewind();
    EXPECT_EQ(-123456789, buf.getInt());
    EXPECT_EQ(4000000000u, buf.getUInt());
}

TEST(ByteBufferPutGet, Long)
{
    ByteBuffer buf = makeBuffer(16);
    buf.putLong(INT64_MIN).putULong(UINT64_MAX);
    buf.rewind();
    EXPECT_EQ(INT64_MIN, buf.getLong());
    EXPECT_EQ(UINT64_MAX, buf.getULong());
}

TEST(ByteBufferPutGet, FloatAndDouble)
{
    ByteBuffer buf = makeBuffer(12);
    buf.putFloat(42.42f).putDouble(-3.14159265358979);
    buf.rewind();
    EXPECT_FLOAT_EQ(42.42f, buf.getFloat());
    EXPECT_DOUBLE_EQ(-3.14159265358979, buf.getDouble());
}

TEST(ByteBufferPutGet, String)
{
    const std::string input = "Hello World!";
    ByteBuffer buf = makeBuffer(64);
    buf.putString(input);
    // 2-byte length prefix + payload
    EXPECT_EQ(2u + input.size(), buf.position());
    buf.rewind();
    EXPECT_EQ(input, buf.getString());
}

TEST(ByteBufferPutGet, EmptyString)
{
    ByteBuffer buf = makeBuffer(8);
    buf.putString("");
    EXPECT_EQ(2u, buf.position());
    buf.rewind();
    EXPECT_EQ("", buf.getString());
}

TEST(ByteBufferPutGet, MixedSequenceMatchesAdaTest)
{
    // Same sequence as src/ada/src/tests/test_bytebuffers.adb
    ByteBuffer buf = makeBuffer(1024);
    buf.putByte(42);
    buf.putString("Hello World!");
    buf.putUInt(42);
    buf.putString("Hello World!");
    buf.putFloat(42.42f);
    buf.putBool(true);
    buf.putULong(84);

    buf.rewind();
    EXPECT_EQ(42, buf.getByte());
    EXPECT_EQ("Hello World!", buf.getString());
    EXPECT_EQ(42u, buf.getUInt());
    EXPECT_EQ("Hello World!", buf.getString());
    EXPECT_FLOAT_EQ(42.42f, buf.getFloat());
    EXPECT_TRUE(buf.getBool());
    EXPECT_EQ(84u, buf.getULong());
}

TEST(ByteBufferArrays, IntArray)
{
    const int32_t in[3] = {-1, 0, 0x01020304};
    int32_t out[3] = {};
    ByteBuffer buf = makeBuffer(12);
    buf.putIntArray(in, 3);
    EXPECT_EQ(12u, buf.position());
    buf.rewind();
    buf.getIntArray(out, 3);
    for (int i = 0; i < 3; ++i) EXPECT_EQ(in[i], out[i]);
}

TEST(ByteBufferArrays, DoubleArray)
{
    const double in[2] = {1.5, -2.25};
    double out[2] = {};
    ByteBuffer buf = makeBuffer(16);
    buf.putDoubleArray(in, 2);
    buf.rewind();
    buf.getDoubleArray(out, 2);
    EXPECT_DOUBLE_EQ(in[0], out[0]);
    EXPECT_DOUBLE_EQ(in[1], out[1]);
}

TEST(ByteBufferArrays, ByteArray)
{
    const uint8_t in[4] = {1, 2, 3, 4};
    uint8_t out[4] = {};
    ByteBuffer buf = makeBuffer(4);
    buf.putByteArray(in, 4);
    buf.rewind();
    buf.getByteArray(out, 4);
    EXPECT_EQ(0, std::memcmp(in, out, 4));
}

TEST(ByteBufferEndianness, BigEndianLayout)
{
    ByteBuffer buf = makeBuffer(8, ByteBuffer::ENDIAN_BIG);
    buf.putUInt(0x01020304u);
    buf.putUShort(0x0A0B);
    const uint8_t* raw = buf.array();
    EXPECT_EQ(0x01, raw[0]);
    EXPECT_EQ(0x02, raw[1]);
    EXPECT_EQ(0x03, raw[2]);
    EXPECT_EQ(0x04, raw[3]);
    EXPECT_EQ(0x0A, raw[4]);
    EXPECT_EQ(0x0B, raw[5]);
}

TEST(ByteBufferEndianness, LittleEndianLayout)
{
    ByteBuffer buf = makeBuffer(8, ByteBuffer::ENDIAN_LITTLE);
    EXPECT_EQ(ByteBuffer::ENDIAN_LITTLE, buf.getByteOrder());
    buf.putUInt(0x01020304u);
    const uint8_t* raw = buf.array();
    EXPECT_EQ(0x04, raw[0]);
    EXPECT_EQ(0x03, raw[1]);
    EXPECT_EQ(0x02, raw[2]);
    EXPECT_EQ(0x01, raw[3]);
    buf.rewind();
    EXPECT_EQ(0x01020304u, buf.getUInt());
}

TEST(ByteBufferEndianness, SixtyFourBitBigEndian)
{
    ByteBuffer buf = makeBuffer(8);
    buf.putULong(0x0102030405060708ull);
    const uint8_t* raw = buf.array();
    for (int i = 0; i < 8; ++i) EXPECT_EQ(i + 1, raw[i]);
}

TEST(ByteBufferBounds, OverflowingPutIsRejected)
{
    ByteBuffer buf = makeBuffer(3);
    buf.putInt(0x11223344); // needs 4 bytes, only 3 available
    EXPECT_EQ(0u, buf.position());
    buf.putShort(1);
    EXPECT_EQ(2u, buf.position());
    buf.putShort(2); // 1 byte left, rejected
    EXPECT_EQ(2u, buf.position());
}

TEST(ByteBufferBounds, UnderflowingGetReturnsZero)
{
    ByteBuffer buf = makeBuffer(2);
    buf.putShort(0x1234);
    // position == 2 == capacity, nothing left
    EXPECT_EQ(0, buf.getInt());
    EXPECT_EQ(0u, buf.getULong());
    EXPECT_EQ(0.0f, buf.getFloat());
}

TEST(ByteBufferBounds, UnallocatedBufferIsInert)
{
    ByteBuffer buf;
    buf.putInt(5);
    EXPECT_EQ(0u, buf.position());
    EXPECT_EQ(0, buf.getInt());
}

TEST(ByteBufferCopy, CopyConstructorCopiesContentAndRewinds)
{
    ByteBuffer a = makeBuffer(8, ByteBuffer::ENDIAN_LITTLE);
    a.putUInt(0xDEADBEEFu);
    ByteBuffer b(a);
    EXPECT_EQ(a.capacity(), b.capacity());
    EXPECT_EQ(0u, b.position());
    EXPECT_EQ(ByteBuffer::ENDIAN_LITTLE, b.getByteOrder());
    EXPECT_EQ(0xDEADBEEFu, b.getUInt());
    EXPECT_NE(a.array(), b.array());
}

TEST(ByteBufferCopy, AssignmentCopiesContent)
{
    ByteBuffer a = makeBuffer(4);
    a.putUInt(0xCAFEBABEu);
    ByteBuffer b;
    b = a;
    EXPECT_EQ(0xCAFEBABEu, b.getUInt());
}

TEST(ByteBufferCopy, PutBufferTransfersRemaining)
{
    ByteBuffer src = makeBuffer(4);
    src.putUInt(0x01020304u);
    src.rewind();
    ByteBuffer dst = makeBuffer(8);
    dst.put(src);
    EXPECT_EQ(4u, dst.position());
    dst.rewind();
    EXPECT_EQ(0x01020304u, dst.getUInt());
}
