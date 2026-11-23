from helpers import *  # noqa
import base64
from uxdiff import lmcp


def test_series_roundtrip():
    assert lmcp.series_name_from_id(lmcp.series_id_from_name("CMASI")) == "CMASI"


def test_frame_roundtrip_and_checksum():
    f = lmcp.key_value_pair_frame("k", "v")
    h = lmcp.parse_frame(f)
    assert h.object_id == ("CMASI", 2, 3)
    assert h.checksum_ok
    assert lmcp.Reader(h.body).string() == "k"
    bad = bytearray(f)
    bad[-1] ^= 0xFF
    assert not lmcp.parse_frame(bytes(bad)).checksum_ok


def test_malformed_frames():
    for data in (b"", b"x" * 40, b"\x4c\x4d\x43\x50" + b"\0" * 8):
        with raises(lmcp.LmcpError):
            lmcp.parse_frame(data)


def test_envelope_roundtrip_binary_payload_with_dollar():
    payload = lmcp.build_frame("CMASI", 2, 3, lmcp.pack_string("a$b|c"))
    env = lmcp.Envelope("addr", payload, source_entity_id=7, source_service_id=9)
    back = lmcp.parse_envelope(env.pack())
    assert back.payload == payload and back.source_entity_id == 7
    assert back.descriptor == "addr"


def test_bad_envelope():
    for raw in (b"nodollar", b"a$b$c", b"a$lmcp|d|g|x|1$p"):
        with raises(lmcp.LmcpError):
            lmcp.parse_envelope(raw)
