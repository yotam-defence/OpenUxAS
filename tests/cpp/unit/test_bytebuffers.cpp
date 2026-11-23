// GoogleTest port of the checks in LmcpGen's Ada test_bytebuffers.adb, run
// against the C++ avtas::lmcp::ByteBuffer shipped in liblmcp.
//
// Semantics worth knowing (they are what the tests pin down):
//   * a ByteBuffer starts with capacity 0; call allocate(n) first;
//   * puts/gets that do not fit are silently ignored (position unchanged);
//     gets return 0 / empty on failure;
//   * position(pos) is ignored when pos >= capacity();
//   * the default byte order is big endian (byte-layout tests assume a
//     little-endian host, as do all supported platforms).

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

#include "avtas/lmcp/ByteBuffer.h"

using avtas::lmcp::ByteBuffer;

namespace {

ByteBuffer makeBuffer(uint32_t size, ByteBuffer::ByteOrder order = ByteBuffer::ENDIAN_BIG)
{
    ByteBuffer b(order);
    b.allocate(size);
    return b;
}

} // namespace

TEST(ByteBufferBasics, StartsEmpty)
{
    ByteBuffer b;
    EXPECT_EQ(0u, b.capacity());
    EXPECT_EQ(0u, b.position());
    EXPECT_FALSE(b.hasRemaining());
    EXPECT_EQ(ByteBuffer::ENDIAN_BIG, b.getByteOrder());
}

TEST(ByteBufferBasics, AllocateSetsCapacityAndRemaining)
{
    ByteBuffer b = makeBuffer(16);
    EXPECT_EQ(16u, b.capacity());
    EXPECT_EQ(16u, b.remaining());
    EXPECT_TRUE(b.hasRemaining());
    b.putInt(1);
    EXPECT_EQ(4u, b.position());
    EXPECT_EQ(12u, b.remaining());
}

TEST(ByteBufferBasics, ClearReleasesStorage)
{
    ByteBuffer b = makeBuffer(8);
    b.putLong(7);
    b.clear();
    // Note: position() is deliberately not checked here; position(0) is
    // rejected on a zero-capacity buffer, so clear() leaves a stale position.
    EXPECT_EQ(0u, b.capacity());
    EXPECT_EQ(nullptr, b.array());
}

TEST(ByteBufferRoundTrip, GetAfterRewind)
{
    ByteBuffer b = makeBuffer(100);
    b.putUShort(42);
    b.rewind();
    EXPECT_EQ(0u, b.position());
    EXPECT_EQ(42u, b.getUShort());
}

TEST(ByteBufferRoundTrip, Primitives)
{
    ByteBuffer b = makeBuffer(64);
    b.putBool(true).putBool(false).putByte(0xAB);
    b.putShort(-1234).putUShort(65000);
    b.putInt(-123456789).putUInt(4000000000u);
    b.putLong(-1234567890123456789LL).putULong(18000000000000000000ULL);
    b.putFloat(3.5f).putDouble(-2.25e100);
    b.rewind();

    EXPECT_TRUE(b.getBool());
    EXPECT_FALSE(b.getBool());
    EXPECT_EQ(0xABu, b.getByte());
    EXPECT_EQ(-1234, b.getShort());
    EXPECT_EQ(65000u, b.getUShort());
    EXPECT_EQ(-123456789, b.getInt());
    EXPECT_EQ(4000000000u, b.getUInt());
    EXPECT_EQ(-1234567890123456789LL, b.getLong());
    EXPECT_EQ(18000000000000000000ULL, b.getULong());
    EXPECT_FLOAT_EQ(3.5f, b.getFloat());
    EXPECT_DOUBLE_EQ(-2.25e100, b.getDouble());
}

TEST(ByteBufferRoundTrip, ExtremeValues)
{
    ByteBuffer b = makeBuffer(64);
    b.putInt(std::numeric_limits<int32_t>::min());
    b.putInt(std::numeric_limits<int32_t>::max());
    b.putLong(std::numeric_limits<int64_t>::min());
    b.putULong(std::numeric_limits<uint64_t>::max());
    b.putDouble(std::numeric_limits<double>::infinity());
    b.putFloat(std::numeric_limits<float>::lowest());
    b.rewind();
    EXPECT_EQ(std::numeric_limits<int32_t>::min(), b.getInt());
    EXPECT_EQ(std::numeric_limits<int32_t>::max(), b.getInt());
    EXPECT_EQ(std::numeric_limits<int64_t>::min(), b.getLong());
    EXPECT_EQ(std::numeric_limits<uint64_t>::max(), b.getULong());
    EXPECT_TRUE(std::isinf(b.getDouble()));
    EXPECT_FLOAT_EQ(std::numeric_limits<float>::lowest(), b.getFloat());
}

TEST(ByteBufferRoundTrip, SingleByteGetPut)
{
    ByteBuffer b = makeBuffer(4);
    b.put(static_cast<uint8_t>(1)).put(static_cast<uint8_t>(2));
    b.rewind();
    EXPECT_EQ(1u, b.get());
    EXPECT_EQ(2u, b.get());
}

TEST(ByteBufferStrings, RoundTrip)
{
    ByteBuffer b = makeBuffer(64);
    b.putString("Hello World!");
    // 2-byte length prefix + content
    EXPECT_EQ(2u + 12u, b.position());
    b.rewind();
    EXPECT_EQ("Hello World!", b.getString());
}

TEST(ByteBufferStrings, EmptyString)
{
    ByteBuffer b = makeBuffer(8);
    b.putString("");
    EXPECT_EQ(2u, b.position());
    b.rewind();
    EXPECT_EQ("", b.getString());
}

TEST(ByteBufferStrings, StringFollowedByValues)
{
    const std::string s = "Hello World!";
    ByteBuffer b = makeBuffer(100);
    b.putString(s).putUInt(42).putByte(42);
    b.rewind();
    EXPECT_EQ(s, b.getString());
    EXPECT_EQ(42u, b.getUInt());
    EXPECT_EQ(42u, b.getByte());
}

TEST(ByteBufferStrings, TooLongForBufferIsIgnored)
{
    ByteBuffer b = makeBuffer(4);
    b.putString("abcdefgh");
    EXPECT_EQ(0u, b.position());
}

TEST(ByteBufferArrays, IntArrayRoundTrip)
{
    const int32_t in[] = {1, -2, 3, std::numeric_limits<int32_t>::min()};
    int32_t out[4] = {0, 0, 0, 0};
    ByteBuffer b = makeBuffer(16);
    b.putIntArray(in, 4);
    EXPECT_EQ(16u, b.position());
    b.rewind();
    b.getIntArray(out, 4);
    for (int i = 0; i < 4; ++i) EXPECT_EQ(in[i], out[i]);
}

TEST(ByteBufferArrays, AllElementTypes)
{
    const bool bo[] = {true, false, true};
    const uint8_t by[] = {1, 2, 255};
    const int16_t sh[] = {-1, 2, -3};
    const uint16_t us[] = {1, 2, 65535};
    const uint32_t ui[] = {1, 2, 4294967295u};
    const int64_t lo[] = {-1, 2, -3};
    const uint64_t ul[] = {1, 2, 18446744073709551615ULL};
    const float fl[] = {1.5f, -2.5f, 0.f};
    const double db[] = {1.5, -2.5, 1e300};

    ByteBuffer b = makeBuffer(256);
    b.putBoolArray(bo, 3).putByteArray(by, 3).putShortArray(sh, 3)
     .putUShortArray(us, 3).putUIntArray(ui, 3).putLongArray(lo, 3)
     .putULongArray(ul, 3).putFloatArray(fl, 3).putDoubleArray(db, 3);
    b.rewind();

    bool rbo[3]; uint8_t rby[3]; int16_t rsh[3]; uint16_t rus[3];
    uint32_t rui[3]; int64_t rlo[3]; uint64_t rul[3]; float rfl[3]; double rdb[3];
    b.getBoolArray(rbo, 3).getByteArray(rby, 3).getShortArray(rsh, 3)
     .getUShortArray(rus, 3).getUIntArray(rui, 3).getLongArray(rlo, 3)
     .getULongArray(rul, 3).getFloatArray(rfl, 3).getDoubleArray(rdb, 3);

    for (int i = 0; i < 3; ++i) {
        EXPECT_EQ(bo[i], rbo[i]);
        EXPECT_EQ(by[i], rby[i]);
        EXPECT_EQ(sh[i], rsh[i]);
        EXPECT_EQ(us[i], rus[i]);
        EXPECT_EQ(ui[i], rui[i]);
        EXPECT_EQ(lo[i], rlo[i]);
        EXPECT_EQ(ul[i], rul[i]);
        EXPECT_FLOAT_EQ(fl[i], rfl[i]);
        EXPECT_DOUBLE_EQ(db[i], rdb[i]);
    }
}

TEST(ByteBufferArrays, BulkPutGet)
{
    const uint8_t in[] = {9, 8, 7, 6};
    uint8_t out[4] = {0};
    ByteBuffer b = makeBuffer(8);
    b.put(in, 4);
    b.rewind();
    b.get(out, 4);
    for (int i = 0; i < 4; ++i) EXPECT_EQ(in[i], out[i]);
}

TEST(ByteBufferEndianness, BigEndianLayout)
{
    ByteBuffer b = makeBuffer(16, ByteBuffer::ENDIAN_BIG);
    b.putUShort(0x0102).putUInt(0x03040506u).putULong(0x0708090A0B0C0D0EULL);
    const uint8_t* a = b.array();
    const uint8_t expected[] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06,
                                0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E};
    for (size_t i = 0; i < sizeof(expected); ++i) EXPECT_EQ(expected[i], a[i]) << i;
}

TEST(ByteBufferEndianness, LittleEndianLayout)
{
    ByteBuffer b = makeBuffer(16, ByteBuffer::ENDIAN_LITTLE);
    b.putUShort(0x0102).putUInt(0x03040506u);
    const uint8_t* a = b.array();
    const uint8_t expected[] = {0x02, 0x01, 0x06, 0x05, 0x04, 0x03};
    for (size_t i = 0; i < sizeof(expected); ++i) EXPECT_EQ(expected[i], a[i]) << i;
}

TEST(ByteBufferEndianness, LittleEndianRoundTrip)
{
    ByteBuffer b = makeBuffer(32, ByteBuffer::ENDIAN_LITTLE);
    const int32_t arr[] = {1, -2, 3};
    int32_t out[3] = {0};
    b.putLong(-5).putDouble(1.25).putIntArray(arr, 3);
    b.rewind();
    EXPECT_EQ(-5, b.getLong());
    EXPECT_DOUBLE_EQ(1.25, b.getDouble());
    b.getIntArray(out, 3);
    for (int i = 0; i < 3; ++i) EXPECT_EQ(arr[i], out[i]);
}

TEST(ByteBufferEndianness, OrdersProduceDifferentBytesForSameValue)
{
    ByteBuffer big = makeBuffer(4, ByteBuffer::ENDIAN_BIG);
    ByteBuffer little = makeBuffer(4, ByteBuffer::ENDIAN_LITTLE);
    big.putUInt(1);
    little.putUInt(1);
    EXPECT_EQ(1u, big.array()[3]);
    EXPECT_EQ(1u, little.array()[0]);
}

TEST(ByteBufferAbsolute, GetAtIndexDoesNotMovePosition)
{
    ByteBuffer b = makeBuffer(16);
    b.putByte(10).putByte(20).putByte(30);
    b.rewind();
    EXPECT_EQ(20u, b.get(1));
    EXPECT_EQ(0u, b.position());
}

TEST(ByteBufferAbsolute, PutAtIndexDoesNotMovePosition)
{
    ByteBuffer b = makeBuffer(4);
    b.put(2u, static_cast<uint8_t>(0x7F));
    EXPECT_EQ(0u, b.position());
    EXPECT_EQ(0x7Fu, b.array()[2]);
}

TEST(ByteBufferBounds, PutBeyondCapacityIsIgnored)
{
    ByteBuffer b = makeBuffer(3);
    b.putInt(1);  // needs 4 bytes
    EXPECT_EQ(0u, b.position());
    b.putUShort(7);  // fits
    EXPECT_EQ(2u, b.position());
    b.putUShort(8);  // only 1 byte left
    EXPECT_EQ(2u, b.position());
}

TEST(ByteBufferBounds, GetBeyondCapacityReturnsZero)
{
    ByteBuffer b = makeBuffer(2);
    b.putUShort(0xFFFF);
    b.rewind();
    EXPECT_EQ(0u, b.getUInt());  // needs 4 bytes
    EXPECT_EQ(0u, b.position());
    EXPECT_EQ(0xFFFFu, b.getUShort());
    EXPECT_FALSE(b.hasRemaining());
    EXPECT_EQ(0u, b.getByte());
}

TEST(ByteBufferBounds, ArrayLargerThanRemainingIsIgnored)
{
    const int32_t in[] = {1, 2, 3, 4};
    ByteBuffer b = makeBuffer(8);
    b.putIntArray(in, 4);
    EXPECT_EQ(0u, b.position());
}

TEST(ByteBufferBounds, UnallocatedBufferIgnoresEverything)
{
    ByteBuffer b;
    b.putInt(5);
    EXPECT_EQ(0u, b.position());
    EXPECT_EQ(0, b.getInt());
}

TEST(ByteBufferBounds, PositionOutOfRangeIsIgnored)
{
    ByteBuffer b = makeBuffer(8);
    b.position(4);
    EXPECT_EQ(4u, b.position());
    b.position(8);  // == capacity, rejected
    EXPECT_EQ(4u, b.position());
    b.position(100);
    EXPECT_EQ(4u, b.position());
}

TEST(ByteBufferCopy, CopyConstructorCopiesContentAndOrder)
{
    ByteBuffer a = makeBuffer(8, ByteBuffer::ENDIAN_LITTLE);
    a.putUInt(0xCAFEBABEu);
    ByteBuffer c(a);
    EXPECT_EQ(a.capacity(), c.capacity());
    EXPECT_EQ(ByteBuffer::ENDIAN_LITTLE, c.getByteOrder());
    EXPECT_EQ(0u, c.position());
    EXPECT_EQ(0xCAFEBABEu, c.getUInt());
    // deep copy: mutating the copy leaves the original untouched
    const uint32_t idx = 0;
    c.put(idx, static_cast<uint8_t>(0));
    EXPECT_EQ(0xBEu, a.array()[0]);
}

TEST(ByteBufferCopy, AssignmentCopiesContent)
{
    ByteBuffer a = makeBuffer(4);
    a.putUInt(77);
    ByteBuffer b;
    b = a;
    EXPECT_EQ(4u, b.capacity());
    EXPECT_EQ(77u, b.getUInt());
}

TEST(ByteBufferCopy, PutBufferAppendsRemainingBytes)
{
    ByteBuffer src = makeBuffer(4);
    src.putUInt(0x01020304u);
    src.rewind();
    ByteBuffer dst = makeBuffer(8);
    dst.putByte(0xEE);
    dst.put(src);
    EXPECT_EQ(5u, dst.position());
    EXPECT_EQ(0xEEu, dst.array()[0]);
    EXPECT_EQ(0x01u, dst.array()[1]);
    EXPECT_EQ(0x04u, dst.array()[4]);
}
