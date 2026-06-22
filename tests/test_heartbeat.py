"""
Tests for the HEARTBEAT control-plane message.

A heartbeat is the common 24-byte header (msg_type=HEARTBEAT, no payload) plus CRC — a
node liveness / clock beacon. These checks pin its on-wire shape and confirm it does not
disturb the SAMPLE_BLOCK data plane.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from wiredaq.protocol.codec import (  # noqa: E402
    HEADER_SIZE,
    MSG_HEARTBEAT,
    MSG_SAMPLE_BLOCK,
    CrcError,
    FramingError,
    crc16_ccitt_false,
    decode,
    encode_heartbeat,
)


def test_heartbeat_is_header_plus_crc_only():
    frame = encode_heartbeat(node_id=7, seq=42, t_node_us=1_000_000, sample_rate_hz=3200)
    assert len(frame) == HEADER_SIZE + 2          # 26 bytes, no payload
    assert frame[:2] == b"WD"
    assert frame[3] == MSG_HEARTBEAT


def test_heartbeat_round_trips():
    frame = encode_heartbeat(node_id=7, seq=42, t_node_us=123456789, sample_rate_hz=3200)
    pkt = decode(frame)
    assert pkt.is_heartbeat
    assert pkt.msg_type == MSG_HEARTBEAT
    assert (pkt.node_id, pkt.seq, pkt.t_node_us, pkt.sample_rate_hz) == (
        7, 42, 123456789, 3200)
    assert pkt.samples == []
    assert pkt.sample_count == 0


def test_heartbeat_crc_is_checked():
    frame = bytearray(encode_heartbeat(node_id=1, seq=0, t_node_us=0))
    frame[10] ^= 0x01                              # corrupt the t_node_us field
    with pytest.raises(CrcError):
        decode(bytes(frame))


def test_sample_block_is_not_a_heartbeat():
    from wiredaq.protocol.codec import encode_sample_block
    pkt = decode(encode_sample_block(node_id=1, seq=0, t_node_us=0, sample_rate_hz=1000,
                                     channel_count=1, samples=[[5]]))
    assert pkt.msg_type == MSG_SAMPLE_BLOCK
    assert not pkt.is_heartbeat


def test_unknown_msg_type_still_rejected():
    # msg_type=3 (DEVICE_INFO) is reserved but not yet decodable.
    frame = bytearray(encode_heartbeat(node_id=1, seq=0, t_node_us=0))
    frame[3] = 3
    # fix the CRC so it's specifically the msg_type that's rejected, not corruption
    crc = crc16_ccitt_false(bytes(frame[:-2]))
    frame[-2] = crc & 0xFF
    frame[-1] = (crc >> 8) & 0xFF
    with pytest.raises(FramingError):
        decode(bytes(frame))
