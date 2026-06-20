"""
WireDAQ wire-format reference encoder — the test oracle for the wire format.

This is NOT the production codec. It is the canonical, deliberately simple
implementation of the layout described in `protocol/packet_schema.yaml`, used to
*generate and verify* the golden vectors in `protocol/golden/vectors.json`.

Both the Python simulator codec (tools/daq_sim) and the C firmware codec must
reproduce these vectors byte-for-byte.

Wire layout (little-endian, packed, no padding):

  offset  size  field           notes
  ------  ----  --------------  --------------------------------------------
  0       2     magic           0x57 0x44  ('WD') frame sync word
  2       1     version         protocol version (1)
  3       1     msg_type        1 = SAMPLE_BLOCK
  4       2     node_id         uint16
  6       4     seq             uint32, per-node, increments per packet
  10      8     t_node_us       uint64, node-local microseconds at first sample
  18      4     sample_rate_hz  uint32
  22      1     channel_count   uint8
  23      1     sample_count    uint8
  24      ...   payload         sample_count * channel_count * int16
  N-2     2     crc16           CRC-16/CCITT-FALSE over bytes[0 .. N-3]

The CRC covers every byte before the CRC field itself, including the magic.
"""

import json
import struct
from pathlib import Path

MAGIC = b"\x57\x44"
VERSION = 1
MSG_SAMPLE_BLOCK = 1
MAX_PACKET_BYTES = 256
HEADER_FMT = "<2sBBHIQIBB"  # 24 bytes
HEADER_SIZE = struct.calcsize(HEADER_FMT)
assert HEADER_SIZE == 24, HEADER_SIZE


def crc16_ccitt_false(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, xorout 0x0000."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def encode_sample_block(
    node_id: int,
    seq: int,
    t_node_us: int,
    sample_rate_hz: int,
    channel_count: int,
    samples: list[list[int]],
) -> bytes:
    """Encode one SAMPLE_BLOCK frame and return the full bytes including CRC."""
    sample_count = len(samples)
    if not (0 <= sample_count <= 0xFF):
        raise ValueError("sample_count must fit in uint8")
    if not (0 <= channel_count <= 0xFF):
        raise ValueError("channel_count must fit in uint8")

    header = struct.pack(
        HEADER_FMT,
        MAGIC,
        VERSION,
        MSG_SAMPLE_BLOCK,
        node_id,
        seq,
        t_node_us,
        sample_rate_hz,
        channel_count,
        sample_count,
    )

    payload = bytearray()
    for row in samples:
        if len(row) != channel_count:
            raise ValueError("each sample must have channel_count values")
        payload += struct.pack("<" + "h" * channel_count, *row)

    frame_wo_crc = header + bytes(payload)
    if len(frame_wo_crc) + 2 > MAX_PACKET_BYTES:
        raise ValueError("frame exceeds MAX_PACKET_BYTES")

    crc = crc16_ccitt_false(frame_wo_crc)
    return frame_wo_crc + struct.pack("<H", crc)


VECTORS = [
    {
        "name": "minimal_single_sample",
        "description": "Smallest valid block: one channel, one sample.",
        "fields": dict(node_id=1, seq=0, t_node_us=0, sample_rate_hz=1000,
                       channel_count=1, samples=[[1000]]),
    },
    {
        "name": "accel_xyz_block",
        "description": "Typical 3-axis accelerometer block, 4 samples, gravity on Z.",
        "fields": dict(node_id=7, seq=42, t_node_us=1234567890, sample_rate_hz=3200,
                       channel_count=3,
                       samples=[[10, -20, 16384], [12, -18, 16380],
                                [-5, 0, 16390], [100, 200, 16000]]),
    },
    {
        "name": "empty_sample_block",
        "description": "Edge case: zero samples (header-only payload, CRC over header).",
        "fields": dict(node_id=7, seq=43, t_node_us=1234890000, sample_rate_hz=3200,
                       channel_count=3, samples=[]),
    },
    {
        "name": "int16_extremes",
        "description": "Two's-complement boundaries to catch signedness bugs.",
        "fields": dict(node_id=255, seq=4294967295, t_node_us=18446744073709551615,
                       sample_rate_hz=48000, channel_count=2,
                       samples=[[-32768, 32767], [0, -1]]),
    },
]


def build_vectors() -> dict:
    out = []
    for v in VECTORS:
        frame = encode_sample_block(**v["fields"])
        crc = crc16_ccitt_false(frame[:-2])
        out.append({
            "name": v["name"],
            "description": v["description"],
            "input": v["fields"],
            "frame_len": len(frame),
            "crc16": f"0x{crc:04X}",
            "frame_hex": frame.hex(),
        })
    return {
        "protocol": "wiredaq",
        "version": VERSION,
        "crc": "CRC-16/CCITT-FALSE",
        "note": "frame_hex is the complete on-wire frame including magic and trailing CRC.",
        "vectors": out,
    }


if __name__ == "__main__":
    assert crc16_ccitt_false(b"123456789") == 0x29B1, "CRC self-test failed"
    print("CRC self-test passed (check value 0x29B1).")

    data = build_vectors()
    out_path = Path(__file__).with_name("vectors.json")
    out_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {len(data['vectors'])} vectors to {out_path}")
    for v in data["vectors"]:
        print(f"  {v['name']:24s} len={v['frame_len']:3d}  crc={v['crc16']}")
