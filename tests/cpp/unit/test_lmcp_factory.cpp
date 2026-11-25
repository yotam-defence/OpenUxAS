// Unit tests for avtas::lmcp::Factory and CMASI message serialization.
//
// Ports the header checks of src/ada/src/tests/test_msg_decode.adb (control
// string, message size, checksum validation, message-present flag, series id,
// message type, version) to run against locally packed messages instead of a
// live ZeroMQ subscription, and adds pack/unpack round trips for a few CMASI
// messages.

#include <gtest/gtest.h>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "avtas/lmcp/ByteBuffer.h"
#include "avtas/lmcp/Factory.h"
#include "avtas/lmcp/Object.h"

#include "afrl/cmasi/AirVehicleState.h"
#include "afrl/cmasi/AltitudeType.h"
#include "afrl/cmasi/AutomationRequest.h"
#include "afrl/cmasi/KeyValuePair.h"
#include "afrl/cmasi/Location3D.h"
#include "afrl/cmasi/MissionCommand.h"
#include "afrl/cmasi/Waypoint.h"

using avtas::lmcp::ByteBuffer;
using avtas::lmcp::Factory;
using avtas::lmcp::Object;

namespace {

uint32_t readBigEndianU32(const uint8_t* p)
{
    return (static_cast<uint32_t>(p[0]) << 24) | (static_cast<uint32_t>(p[1]) << 16) |
           (static_cast<uint32_t>(p[2]) << 8) | static_cast<uint32_t>(p[3]);
}

}  // namespace

class LmcpFactoryTest : public ::testing::Test {
protected:
    // Packs `obj` and returns the buffer (rewound, ready for Factory::getObject).
    static std::unique_ptr<ByteBuffer> pack(const Object& obj, bool checksum)
    {
        std::unique_ptr<ByteBuffer> buf(Factory::packMessage(&obj, checksum));
        if (buf) {
            buf->rewind();
        }
        return buf;
    }

    static std::unique_ptr<Object> unpack(ByteBuffer& buf)
    {
        buf.rewind();
        return std::unique_ptr<Object>(Factory::getObject(buf));
    }

    static afrl::cmasi::KeyValuePair makeKvp()
    {
        afrl::cmasi::KeyValuePair kvp;
        kvp.setKey("Hello");
        kvp.setValue("World!");
        return kvp;
    }
};

// ---- constants -----------------------------------------------------------

TEST_F(LmcpFactoryTest, Constants)
{
    EXPECT_EQ(Factory::HEADER_SIZE, 8u);
    EXPECT_EQ(Factory::CHECKSUM_SIZE, 4u);
    EXPECT_EQ(Factory::SERIESNAME_SIZE, 8u);
    // "LMCP" as a 4-byte big-endian integer. (test_msg_decode.adb compares
    // against the decimal 1634103916 instead; see README "Known gaps".)
    EXPECT_EQ(Factory::LMCP_CONTROL_STR, 0x4c4d4350);
}

// ---- header layout (Test_Msg_Decode port) ----------------------------------

TEST_F(LmcpFactoryTest, PackedHeaderLayout)
{
    auto kvp = makeKvp();
    auto buf = pack(kvp, true);
    ASSERT_NE(buf, nullptr);

    // total = header(8) + 15 object header + payload + checksum(4)
    const uint32_t expectedSize =
        Factory::HEADER_SIZE + kvp.calculatePackedSize() + 15 + Factory::CHECKSUM_SIZE;
    EXPECT_EQ(buf->capacity(), expectedSize);

    // Control string
    EXPECT_EQ(buf->getInt(), Factory::LMCP_CONTROL_STR);
    // Message size (everything between the 8-byte header and the checksum)
    const uint32_t msgSize = buf->getUInt();
    EXPECT_EQ(msgSize, buf->capacity() - Factory::HEADER_SIZE - Factory::CHECKSUM_SIZE);
    EXPECT_LE(msgSize, buf->capacity());
    EXPECT_EQ(Factory::getObjectSize(buf->array(), buf->capacity()), msgSize);

    EXPECT_TRUE(Factory::validate(buf->array(), buf->capacity()));

    // Object header: exists flag, series id, type, version
    EXPECT_TRUE(buf->getBool());
    EXPECT_EQ(buf->getLong(), kvp.getSeriesNameAsLong());
    EXPECT_EQ(buf->getUInt(), kvp.getLmcpType());
    EXPECT_EQ(buf->getUShort(), kvp.getSeriesVersion());
}

TEST_F(LmcpFactoryTest, ControlStringBytesSpellLMCP)
{
    auto kvp = makeKvp();
    auto buf = pack(kvp, false);
    ASSERT_NE(buf, nullptr);
    EXPECT_EQ(buf->get(0u), 'L');
    EXPECT_EQ(buf->get(1u), 'M');
    EXPECT_EQ(buf->get(2u), 'C');
    EXPECT_EQ(buf->get(3u), 'P');
}

TEST_F(LmcpFactoryTest, SeriesNameAsLongEncodesSeriesName)
{
    auto kvp = makeKvp();
    EXPECT_EQ(kvp.getSeriesName(), "CMASI");
    // Series name is packed as big-endian ASCII, left-aligned, zero padded.
    const int64_t id = kvp.getSeriesNameAsLong();
    const uint64_t u = static_cast<uint64_t>(id);
    EXPECT_EQ(static_cast<char>((u >> 56) & 0xFF), 'C');
    EXPECT_EQ(static_cast<char>((u >> 48) & 0xFF), 'M');
    EXPECT_EQ(static_cast<char>((u >> 40) & 0xFF), 'A');
    EXPECT_EQ(static_cast<char>((u >> 32) & 0xFF), 'S');
    EXPECT_EQ(static_cast<char>((u >> 24) & 0xFF), 'I');
}

// ---- checksum --------------------------------------------------------------

TEST_F(LmcpFactoryTest, ChecksumDisabledWritesZeroAndValidates)
{
    auto kvp = makeKvp();
    auto buf = pack(kvp, false);
    ASSERT_NE(buf, nullptr);
    const uint32_t cs = readBigEndianU32(buf->array() + buf->capacity() - 4);
    EXPECT_EQ(cs, 0u);
    EXPECT_TRUE(Factory::validate(buf->array(), buf->capacity()));
}

TEST_F(LmcpFactoryTest, ChecksumEnabledMatchesCalculatedSum)
{
    auto kvp = makeKvp();
    auto buf = pack(kvp, true);
    ASSERT_NE(buf, nullptr);

    uint32_t expected = 0;
    for (uint32_t i = 0; i < buf->capacity() - Factory::CHECKSUM_SIZE; ++i) {
        expected += buf->array()[i];
    }
    EXPECT_EQ(Factory::calculateChecksum(buf->array(), buf->capacity()), expected);
    EXPECT_EQ(readBigEndianU32(buf->array() + buf->capacity() - 4), expected);
    EXPECT_TRUE(Factory::validate(buf->array(), buf->capacity()));
}

TEST_F(LmcpFactoryTest, CorruptedPayloadFailsValidation)
{
    auto kvp = makeKvp();
    auto buf = pack(kvp, true);
    ASSERT_NE(buf, nullptr);
    // Flip a payload byte (past the 8-byte header + 15-byte object header).
    buf->put(static_cast<uint32_t>(Factory::HEADER_SIZE + 15 + 3),
             static_cast<uint8_t>(buf->get(Factory::HEADER_SIZE + 15 + 3) ^ 0xFF));
    EXPECT_FALSE(Factory::validate(buf->array(), buf->capacity()));
    EXPECT_EQ(unpack(*buf), nullptr);
}

TEST_F(LmcpFactoryTest, ValidateRejectsTooShortBuffer)
{
    const uint8_t tiny[11] = {};  // HEADER_SIZE + CHECKSUM_SIZE - 1
    EXPECT_FALSE(Factory::validate(tiny, sizeof(tiny)));
}

TEST_F(LmcpFactoryTest, GetObjectSizeOnShortBufferIsZero)
{
    const uint8_t tiny[4] = {0, 0, 0, 1};
    EXPECT_EQ(Factory::getObjectSize(tiny, sizeof(tiny)), 0u);
}

// ---- malformed input -------------------------------------------------------

TEST_F(LmcpFactoryTest, PackNullObjectReturnsNull)
{
    EXPECT_EQ(Factory::packMessage(nullptr, true), nullptr);
}

TEST_F(LmcpFactoryTest, GetObjectRejectsWrongControlString)
{
    auto kvp = makeKvp();
    auto buf = pack(kvp, true);
    ASSERT_NE(buf, nullptr);
    buf->put(static_cast<uint32_t>(0), static_cast<uint8_t>('X'));
    EXPECT_EQ(unpack(*buf), nullptr);
}

TEST_F(LmcpFactoryTest, GetObjectRejectsBufferSmallerThanHeaderPlusChecksum)
{
    ByteBuffer small;
    small.allocate(Factory::HEADER_SIZE + Factory::CHECKSUM_SIZE - 1);
    EXPECT_EQ(unpack(small), nullptr);
}

TEST_F(LmcpFactoryTest, GetObjectRejectsOversizedMessageLength)
{
    auto kvp = makeKvp();
    auto buf = pack(kvp, false);
    ASSERT_NE(buf, nullptr);
    // Overwrite the size field with something bigger than the buffer.
    buf->put(static_cast<uint32_t>(4), static_cast<uint8_t>(0x7F));
    EXPECT_EQ(unpack(*buf), nullptr);
}

TEST_F(LmcpFactoryTest, GetObjectReturnsNullForNullMarker)
{
    // Hand-build a message whose "object present" flag is false.
    ByteBuffer buf;
    buf.allocate(Factory::HEADER_SIZE + 1 + Factory::CHECKSUM_SIZE);
    buf.putInt(Factory::LMCP_CONTROL_STR);
    buf.putUInt(1);
    buf.putBool(false);
    buf.putUInt(0);  // checksum disabled
    EXPECT_EQ(unpack(buf), nullptr);
}

TEST_F(LmcpFactoryTest, CreateObjectUnknownTypeReturnsNull)
{
    auto kvp = makeKvp();
    std::unique_ptr<Object> o(
        Factory::createObject(kvp.getSeriesNameAsLong(), 0xFFFFFFF0u, kvp.getSeriesVersion()));
    EXPECT_EQ(o, nullptr);
}

TEST_F(LmcpFactoryTest, CreateObjectUnknownSeriesReturnsNull)
{
    auto kvp = makeKvp();
    std::unique_ptr<Object> o(Factory::createObject(0x1234567812345678LL, kvp.getLmcpType(),
                                                    kvp.getSeriesVersion()));
    EXPECT_EQ(o, nullptr);
}

// ---- factory creation ------------------------------------------------------

TEST_F(LmcpFactoryTest, CreateObjectMakesRequestedType)
{
    afrl::cmasi::Location3D proto;
    std::unique_ptr<Object> o(
        Factory::createObject(proto.getSeriesNameAsLong(), proto.getLmcpType(), proto.getSeriesVersion()));
    ASSERT_NE(o, nullptr);
    EXPECT_EQ(o->getLmcpType(), proto.getLmcpType());
    EXPECT_EQ(o->getLmcpTypeName(), "Location3D");
    EXPECT_EQ(o->getFullLmcpTypeName(), "afrl.cmasi.Location3D");
    EXPECT_NE(dynamic_cast<afrl::cmasi::Location3D*>(o.get()), nullptr);
}

TEST_F(LmcpFactoryTest, DistinctMessagesHaveDistinctTypeIds)
{
    afrl::cmasi::KeyValuePair kvp;
    afrl::cmasi::Location3D loc;
    afrl::cmasi::Waypoint wp;
    afrl::cmasi::MissionCommand mc;
    afrl::cmasi::AirVehicleState avs;
    std::vector<uint32_t> ids = {kvp.getLmcpType(), loc.getLmcpType(), wp.getLmcpType(),
                                 mc.getLmcpType(), avs.getLmcpType()};
    for (size_t i = 0; i < ids.size(); ++i) {
        for (size_t j = i + 1; j < ids.size(); ++j) {
            EXPECT_NE(ids[i], ids[j]) << i << " vs " << j;
        }
    }
}

// ---- round trips ------------------------------------------------------------

TEST_F(LmcpFactoryTest, KeyValuePairRoundTrip)
{
    auto kvp = makeKvp();
    auto buf = pack(kvp, true);
    ASSERT_NE(buf, nullptr);
    auto out = unpack(*buf);
    ASSERT_NE(out, nullptr);
    auto* got = dynamic_cast<afrl::cmasi::KeyValuePair*>(out.get());
    ASSERT_NE(got, nullptr);
    EXPECT_EQ(got->getKey(), "Hello");
    EXPECT_EQ(got->getValue(), "World!");
}

TEST_F(LmcpFactoryTest, KeyValuePairRoundTripWithoutChecksum)
{
    auto kvp = makeKvp();
    auto buf = pack(kvp, false);
    ASSERT_NE(buf, nullptr);
    auto out = unpack(*buf);
    ASSERT_NE(out, nullptr);
    auto* got = dynamic_cast<afrl::cmasi::KeyValuePair*>(out.get());
    ASSERT_NE(got, nullptr);
    EXPECT_EQ(got->getKey(), "Hello");
}

TEST_F(LmcpFactoryTest, EmptyStringsRoundTrip)
{
    afrl::cmasi::KeyValuePair kvp;  // default: empty key and value
    auto buf = pack(kvp, true);
    ASSERT_NE(buf, nullptr);
    auto out = unpack(*buf);
    ASSERT_NE(out, nullptr);
    auto* got = dynamic_cast<afrl::cmasi::KeyValuePair*>(out.get());
    ASSERT_NE(got, nullptr);
    EXPECT_EQ(got->getKey(), "");
    EXPECT_EQ(got->getValue(), "");
}

TEST_F(LmcpFactoryTest, Location3DRoundTripPreservesNumbersAndEnum)
{
    afrl::cmasi::Location3D loc;
    loc.setLatitude(45.3125);
    loc.setLongitude(-122.6789012345);
    loc.setAltitude(1234.5f);
    loc.setAltitudeType(afrl::cmasi::AltitudeType::AGL);

    auto buf = pack(loc, true);
    ASSERT_NE(buf, nullptr);
    auto out = unpack(*buf);
    ASSERT_NE(out, nullptr);
    auto* got = dynamic_cast<afrl::cmasi::Location3D*>(out.get());
    ASSERT_NE(got, nullptr);
    EXPECT_EQ(got->getLatitude(), 45.3125);
    EXPECT_EQ(got->getLongitude(), -122.6789012345);
    EXPECT_EQ(got->getAltitude(), 1234.5f);
    EXPECT_EQ(got->getAltitudeType(), afrl::cmasi::AltitudeType::AGL);
}

TEST_F(LmcpFactoryTest, Location3DDefaultAltitudeTypeIsMsl)
{
    afrl::cmasi::Location3D loc;
    EXPECT_EQ(loc.getAltitudeType(), afrl::cmasi::AltitudeType::MSL);
    auto buf = pack(loc, true);
    ASSERT_NE(buf, nullptr);
    auto out = unpack(*buf);
    ASSERT_NE(out, nullptr);
    auto* got = dynamic_cast<afrl::cmasi::Location3D*>(out.get());
    ASSERT_NE(got, nullptr);
    EXPECT_EQ(got->getAltitudeType(), afrl::cmasi::AltitudeType::MSL);
}

TEST_F(LmcpFactoryTest, WaypointRoundTripIncludesInheritedFields)
{
    afrl::cmasi::Waypoint wp;
    wp.setLatitude(1.5);
    wp.setLongitude(2.5);
    wp.setAltitude(300.f);
    wp.setNumber(7);
    wp.setNextWaypoint(8);
    wp.setSpeed(25.f);

    auto buf = pack(wp, true);
    ASSERT_NE(buf, nullptr);
    auto out = unpack(*buf);
    ASSERT_NE(out, nullptr);
    auto* got = dynamic_cast<afrl::cmasi::Waypoint*>(out.get());
    ASSERT_NE(got, nullptr);
    EXPECT_EQ(got->getNumber(), 7);
    EXPECT_EQ(got->getNextWaypoint(), 8);
    EXPECT_EQ(got->getSpeed(), 25.f);
    EXPECT_EQ(got->getLatitude(), 1.5);
    EXPECT_EQ(got->getLongitude(), 2.5);
    EXPECT_EQ(got->getAltitude(), 300.f);
}

TEST_F(LmcpFactoryTest, AirVehicleStateRoundTripWithNestedLocation)
{
    afrl::cmasi::AirVehicleState state;
    state.setID(42);
    state.setHeading(90.f);
    state.setAirspeed(33.25f);
    auto* loc = new afrl::cmasi::Location3D();  // ownership passes to `state`
    loc->setLatitude(10.0);
    loc->setLongitude(20.0);
    loc->setAltitude(500.f);
    state.setLocation(loc);

    auto buf = pack(state, true);
    ASSERT_NE(buf, nullptr);
    auto out = unpack(*buf);
    ASSERT_NE(out, nullptr);
    auto* got = dynamic_cast<afrl::cmasi::AirVehicleState*>(out.get());
    ASSERT_NE(got, nullptr);
    EXPECT_EQ(got->getID(), 42);
    EXPECT_EQ(got->getHeading(), 90.f);
    EXPECT_EQ(got->getAirspeed(), 33.25f);
    ASSERT_NE(got->getLocation(), nullptr);
    EXPECT_EQ(got->getLocation()->getLatitude(), 10.0);
    EXPECT_EQ(got->getLocation()->getLongitude(), 20.0);
    EXPECT_EQ(got->getLocation()->getAltitude(), 500.f);
}

TEST_F(LmcpFactoryTest, MissionCommandRoundTripWithWaypointList)
{
    afrl::cmasi::MissionCommand mc;
    mc.setCommandID(11);
    mc.setVehicleID(3);
    mc.setFirstWaypoint(1);
    for (int64_t n = 1; n <= 3; ++n) {
        auto* wp = new afrl::cmasi::Waypoint();  // owned by `mc`
        wp->setNumber(n);
        wp->setNextWaypoint(n < 3 ? n + 1 : n);
        wp->setLatitude(10.0 * n);
        wp->setLongitude(-5.0 * n);
        mc.getWaypointList().push_back(wp);
    }

    auto buf = pack(mc, true);
    ASSERT_NE(buf, nullptr);
    auto out = unpack(*buf);
    ASSERT_NE(out, nullptr);
    auto* got = dynamic_cast<afrl::cmasi::MissionCommand*>(out.get());
    ASSERT_NE(got, nullptr);
    EXPECT_EQ(got->getCommandID(), 11);
    EXPECT_EQ(got->getVehicleID(), 3);
    EXPECT_EQ(got->getFirstWaypoint(), 1);
    ASSERT_EQ(got->getWaypointList().size(), 3u);
    for (int64_t n = 1; n <= 3; ++n) {
        const auto* wp = got->getWaypointList()[static_cast<size_t>(n - 1)];
        ASSERT_NE(wp, nullptr);
        EXPECT_EQ(wp->getNumber(), n);
        EXPECT_EQ(wp->getNextWaypoint(), n < 3 ? n + 1 : n);
        EXPECT_EQ(wp->getLatitude(), 10.0 * n);
        EXPECT_EQ(wp->getLongitude(), -5.0 * n);
    }
}

TEST_F(LmcpFactoryTest, AutomationRequestRoundTripWithInt64Arrays)
{
    afrl::cmasi::AutomationRequest req;
    req.getEntityList() = {1, 2, 3};
    req.getTaskList() = {100, 200};
    req.setOperatingRegion(9);

    auto buf = pack(req, true);
    ASSERT_NE(buf, nullptr);
    auto out = unpack(*buf);
    ASSERT_NE(out, nullptr);
    auto* got = dynamic_cast<afrl::cmasi::AutomationRequest*>(out.get());
    ASSERT_NE(got, nullptr);
    EXPECT_EQ(got->getEntityList(), (std::vector<int64_t>{1, 2, 3}));
    EXPECT_EQ(got->getTaskList(), (std::vector<int64_t>{100, 200}));
    EXPECT_EQ(got->getOperatingRegion(), 9);
}

TEST_F(LmcpFactoryTest, EmptyListsRoundTrip)
{
    afrl::cmasi::MissionCommand mc;
    auto buf = pack(mc, true);
    ASSERT_NE(buf, nullptr);
    auto out = unpack(*buf);
    ASSERT_NE(out, nullptr);
    auto* got = dynamic_cast<afrl::cmasi::MissionCommand*>(out.get());
    ASSERT_NE(got, nullptr);
    EXPECT_TRUE(got->getWaypointList().empty());
}

// ---- direct pack/unpack and clone -------------------------------------------

TEST_F(LmcpFactoryTest, DirectPackSizeMatchesCalculatedPackedSize)
{
    auto kvp = makeKvp();
    ByteBuffer buf;
    buf.allocate(kvp.calculatePackedSize());
    kvp.pack(buf);
    EXPECT_EQ(buf.position(), buf.capacity());  // exactly filled

    buf.rewind();
    afrl::cmasi::KeyValuePair out;
    out.unpack(buf);
    EXPECT_EQ(out.getKey(), "Hello");
    EXPECT_EQ(out.getValue(), "World!");
}

TEST_F(LmcpFactoryTest, CloneIsDeepCopy)
{
    afrl::cmasi::MissionCommand mc;
    mc.setCommandID(5);
    auto* wp = new afrl::cmasi::Waypoint();
    wp->setNumber(1);
    mc.getWaypointList().push_back(wp);

    std::unique_ptr<Object> copy(mc.clone());
    ASSERT_NE(copy, nullptr);
    auto* c = dynamic_cast<afrl::cmasi::MissionCommand*>(copy.get());
    ASSERT_NE(c, nullptr);
    EXPECT_EQ(c->getCommandID(), 5);
    ASSERT_EQ(c->getWaypointList().size(), 1u);
    EXPECT_NE(c->getWaypointList()[0], mc.getWaypointList()[0]);
    EXPECT_EQ(c->getWaypointList()[0]->getNumber(), 1);

    mc.setCommandID(6);
    EXPECT_EQ(c->getCommandID(), 5);
}

TEST_F(LmcpFactoryTest, RepeatedPackIsDeterministic)
{
    auto kvp = makeKvp();
    auto a = pack(kvp, true);
    auto b = pack(kvp, true);
    ASSERT_NE(a, nullptr);
    ASSERT_NE(b, nullptr);
    ASSERT_EQ(a->capacity(), b->capacity());
    for (uint32_t i = 0; i < a->capacity(); ++i) {
        ASSERT_EQ(a->array()[i], b->array()[i]) << "byte " << i;
    }
}
