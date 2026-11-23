"""Minimal, dependency-free LMCP wire-format helpers.

Wire layout of a full LMCP frame (big endian)::

    uint32  control   0x4C4D4350 ("LMCP")
    uint32  size      bytes following this field, excluding the checksum
    uint8   exists    1 if an object follows
    int64   series    series name packed as 8 ASCII bytes, NUL padded
    uint32  type      object type id inside the series
    uint16  version   series version
    ...     fields
    uint32  checksum  sum of all preceding bytes (mod 2**32)

A message on the UxAS ZeroMQ bus (an *envelope*) is::

    ADDRESS$content_type|descriptor|source_group|entity_id|service_id$FRAME
"""

import struct

CONTROL = 0x4C4D4350
HEADER_LEN = 8
OBJECT_HEADER_LEN = 15  # exists(1) + series(8) + type(4) + version(2)
CHECKSUM_LEN = 4


class LmcpError(ValueError):
    """Raised for malformed LMCP frames or envelopes."""


def series_id_from_name(name):
    """Pack a series name (max 8 chars) into its int64 id."""
    raw = name.encode("ascii")
    if len(raw) > 8:
        raise LmcpError("series name too long: %r" % name)
    return struct.unpack(">q", raw.ljust(8, b"\0"))[0]


def series_name_from_id(series_id):
    """Inverse of :func:`series_id_from_name`."""
    raw = struct.pack(">q", series_id).rstrip(b"\0")
    return raw.decode("ascii", errors="replace")


class Frame(object):
    """A decoded LMCP frame header plus undecoded field bytes."""

    def __init__(self, series_id, type_id, version, size, body, checksum_ok):
        self.series_id = series_id
        self.series = series_name_from_id(series_id)
        self.type_id = type_id
        self.version = version
        self.size = size
        self.body = body  # field bytes only (no header / checksum)
        self.checksum_ok = checksum_ok

    @property
    def object_id(self):
        """Full object identity: (series name, type id, version)."""
        return (self.series, self.type_id, self.version)


def checksum(data):
    return sum(bytearray(data)) & 0xFFFFFFFF


def parse_frame(frame):
    """Decode the header of a full LMCP frame.

    Tolerates the two size conventions seen in the wild (size including or
    excluding the 'exists' byte); the checksum result is reported rather than
    enforced.

    :raises LmcpError: if the frame is truncated or has a bad control word
    """
    frame = bytes(frame)
    if len(frame) < HEADER_LEN + OBJECT_HEADER_LEN + CHECKSUM_LEN:
        raise LmcpError("frame too short (%d bytes)" % len(frame))
    control, size = struct.unpack_from(">II", frame, 0)
    if control != CONTROL:
        raise LmcpError("bad control word 0x%08X" % control)
    exists = frame[HEADER_LEN]
    if exists == 0:
        raise LmcpError("null object")
    series_id, type_id, version = struct.unpack_from(">qIH", frame, HEADER_LEN + 1)
    body = frame[HEADER_LEN + OBJECT_HEADER_LEN:len(frame) - CHECKSUM_LEN]
    (expected,) = struct.unpack_from(">I", frame, len(frame) - CHECKSUM_LEN)
    ok = expected == checksum(frame[:-CHECKSUM_LEN])
    return Frame(series_id, type_id, version, size, body, ok)


def build_frame(series, type_id, version, body=b""):
    """Build a full LMCP frame from already packed field bytes."""
    sid = series_id_from_name(series) if isinstance(series, str) else series
    obj = struct.pack(">BqIH", 1, sid, type_id, version) + bytes(body)
    data = struct.pack(">II", CONTROL, len(obj)) + obj
    return data + struct.pack(">I", checksum(data))


def pack_string(value):
    raw = value.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


class Reader(object):
    """Sequential big-endian reader for field bytes."""

    def __init__(self, data):
        self.data = bytes(data)
        self.pos = 0

    def unpack(self, fmt):
        try:
            vals = struct.unpack_from(fmt, self.data, self.pos)
        except struct.error as exc:
            raise LmcpError("truncated field data: %s" % exc)
        self.pos += struct.calcsize(fmt)
        return vals[0] if len(vals) == 1 else vals

    def string(self):
        n = self.unpack(">H")
        if self.pos + n > len(self.data):
            raise LmcpError("truncated string")
        s = self.data[self.pos:self.pos + n]
        self.pos += n
        return s.decode("utf-8", errors="replace")

    @property
    def at_end(self):
        return self.pos == len(self.data)


class Envelope(object):
    """A ZeroMQ bus message: routing attributes plus an LMCP frame."""

    def __init__(self, address, payload, content_type="lmcp", descriptor=None,
                 source_group="", source_entity_id=0, source_service_id=0):
        self.address = address
        self.payload = payload
        self.content_type = content_type
        self.descriptor = address if descriptor is None else descriptor
        self.source_group = source_group
        self.source_entity_id = int(source_entity_id)
        self.source_service_id = int(source_service_id)

    def pack(self):
        attrs = "|".join([self.content_type, self.descriptor, self.source_group,
                          str(self.source_entity_id),
                          str(self.source_service_id)])
        return (self.address.encode("utf-8") + b"$" + attrs.encode("utf-8") +
                b"$" + bytes(self.payload))


def parse_envelope(raw):
    """Parse a raw ZeroMQ message into an :class:`Envelope`."""
    parts = bytes(raw).split(b"$", 2)
    if len(parts) != 3:
        raise LmcpError("envelope needs ADDRESS$ATTRS$PAYLOAD")
    attrs = parts[1].split(b"|", 4)
    if len(attrs) != 5:
        raise LmcpError("envelope attributes need 5 '|' separated fields")
    try:
        return Envelope(
            address=parts[0].decode("utf-8"),
            payload=parts[2],
            content_type=attrs[0].decode("utf-8"),
            descriptor=attrs[1].decode("utf-8"),
            source_group=attrs[2].decode("utf-8"),
            source_entity_id=int(attrs[3] or 0),
            source_service_id=int(attrs[4] or 0))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LmcpError("bad envelope attributes: %s" % exc)


# --- helpers for well known CMASI objects (used by smoke scenarios) --------

CMASI = "CMASI"
CMASI_VERSION = 3
KEY_VALUE_PAIR_ID = 2
KEY_VALUE_PAIR_ADDRESS = "afrl.cmasi.KeyValuePair"


def key_value_pair_frame(key, value):
    return build_frame(CMASI, KEY_VALUE_PAIR_ID, CMASI_VERSION,
                       pack_string(key) + pack_string(value))
