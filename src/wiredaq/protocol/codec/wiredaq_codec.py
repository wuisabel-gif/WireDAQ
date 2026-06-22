"""
WireDAQ production codec — encode/decode the wire format defined in
``src/wiredaq/protocol/packet_schema.yaml``.

Unlike ``src/wiredaq/protocol/golden/reference_encoder.py`` (the deliberately-simple oracle that
*generates* the golden vectors), this is the codec the running simulator uses. Both must
reproduce ``src/wiredaq/protocol/golden/vectors.json`` byte-for-byte — that equivalence is enforced
by ``tests/test_golden_vectors.py``. The C firmware codec is the third implementation
held to the same vectors.

Wire layout (little-endian, packed, no padding) — see the schema for the authority:

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

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List

# --- constants mirrored from src/wiredaq/protocol/packet_schema.yaml ----------------------
# If the schema changes these, update here and regenerate the golden vectors.
# tests/test_golden_vectors.py is the trip-wire that catches drift between the two.
MAGIC = b"\x57\x44"  # 'WD'
VERSION = 1
MSG_SAMPLE_BLOCK = 1
MSG_HEARTBEAT = 2  # control plane: node liveness / clock beacon (header-only payload)
MAX_PACKET_BYTES = 256

# msg_types this codec will decode. SAMPLE_BLOCK is the data plane; HEARTBEAT is the first
# control-plane message (see packet_schema.yaml). Both share the common 24-byte header, so
# the receiver frames, CRC-checks, and routes by msg_type before knowing the payload shape.
_DECODABLE_MSG_TYPES = (MSG_SAMPLE_BLOCK, MSG_HEARTBEAT)

HEADER_FMT = "<2sBBHIQIBB"  # 24 bytes
HEADER_SIZE = struct.calcsize(HEADER_FMT)
CRC_SIZE = 2
assert HEADER_SIZE == 24, HEADER_SIZE

_CRC_CHECK_VALUE = 0x29B1  # CRC of ASCII "123456789"; sanity-checked on import


class CodecError(Exception):
    """Base class for all wire-format errors."""


class FramingError(CodecError):
    """Magic/version/length is wrong — the bytes are not a valid WireDAQ frame."""


class CrcError(CodecError):
    """The frame's trailing CRC does not match the bytes it covers (corruption)."""

    def __init__(self, expected: int, found: int) -> None:
        super().__init__(f"CRC mismatch: expected 0x{expected:04X}, found 0x{found:04X}")
        self.expected = expected
        self.found = found


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


# Fail loudly at import time if the CRC implementation is wrong — every codec in
# every language must agree on this check value (see the schema's `crc.check`).
assert crc16_ccitt_false(b"123456789") == _CRC_CHECK_VALUE, "CRC self-test failed"


@dataclass
class Packet:
    """A decoded SAMPLE_BLOCK frame: the common currency between Receiver and Sink.

    ``samples`` is a list of rows, one row per sample, each row holding
    ``channel_count`` signed int16 values.
    """

    node_id: int
    seq: int
    t_node_us: int
    sample_rate_hz: int
    channel_count: int
    samples: List[List[int]] = field(default_factory=list)
    msg_type: int = MSG_SAMPLE_BLOCK

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def is_heartbeat(self) -> bool:
        """True if this is a control-plane HEARTBEAT (liveness beacon), not data."""
        return self.msg_type == MSG_HEARTBEAT

    def to_input(self) -> dict:
        """Return the canonical golden-vector ``input`` dict for this packet."""
        return {
            "node_id": self.node_id,
            "seq": self.seq,
            "t_node_us": self.t_node_us,
            "sample_rate_hz": self.sample_rate_hz,
            "channel_count": self.channel_count,
            "samples": [list(row) for row in self.samples],
        }

    def sample_time_us(self, i: int) -> int:
        """Reconstructed node-local timestamp of sample ``i`` within this block.

        Mirrors the schema's per-sample timestamp rule; only one timestamp is sent
        per block, the rest are derived from the declared sample rate.
        """
        if self.sample_rate_hz <= 0:
            return self.t_node_us
        return self.t_node_us + round(i * 1_000_000 / self.sample_rate_hz)


def encode_sample_block(
    node_id: int,
    seq: int,
    t_node_us: int,
    sample_rate_hz: int,
    channel_count: int,
    samples: List[List[int]],
) -> bytes:
    """Encode one SAMPLE_BLOCK frame and return the full bytes including the CRC.

    Signature intentionally matches the golden vectors' ``input`` keys so a vector can
    be replayed with ``encode_sample_block(**vector["input"])``.
    """
    sample_count = len(samples)
    if not (0 <= node_id <= 0xFFFF):
        raise FramingError("node_id must fit in uint16")
    if not (0 <= seq <= 0xFFFFFFFF):
        raise FramingError("seq must fit in uint32")
    if not (0 <= t_node_us <= 0xFFFFFFFFFFFFFFFF):
        raise FramingError("t_node_us must fit in uint64")
    if not (0 <= sample_rate_hz <= 0xFFFFFFFF):
        raise FramingError("sample_rate_hz must fit in uint32")
    if not (0 <= channel_count <= 0xFF):
        raise FramingError("channel_count must fit in uint8")
    if not (0 <= sample_count <= 0xFF):
        raise FramingError("sample_count must fit in uint8")

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
            raise FramingError("each sample must have channel_count values")
        payload += struct.pack("<" + "h" * channel_count, *row)

    frame_wo_crc = header + bytes(payload)
    if len(frame_wo_crc) + CRC_SIZE > MAX_PACKET_BYTES:
        raise FramingError("frame exceeds MAX_PACKET_BYTES")

    crc = crc16_ccitt_false(frame_wo_crc)
    return frame_wo_crc + struct.pack("<H", crc)


def encode_heartbeat(
    node_id: int,
    seq: int,
    t_node_us: int,
    sample_rate_hz: int = 0,
) -> bytes:
    """Encode one HEARTBEAT frame: the common 24-byte header (msg_type=HEARTBEAT, zero
    channels/samples) plus CRC, no payload.

    A heartbeat is a node's liveness / clock beacon. It carries the node's identity, its
    current per-node ``seq`` (so beacons share the data stream's gap detection), and its
    local clock ``t_node_us`` — exactly the fields already in the shared header, which is
    why the payload is empty. The receiver decodes it like any other frame and routes on
    ``msg_type``.
    """
    if not (0 <= node_id <= 0xFFFF):
        raise FramingError("node_id must fit in uint16")
    if not (0 <= seq <= 0xFFFFFFFF):
        raise FramingError("seq must fit in uint32")
    if not (0 <= t_node_us <= 0xFFFFFFFFFFFFFFFF):
        raise FramingError("t_node_us must fit in uint64")
    if not (0 <= sample_rate_hz <= 0xFFFFFFFF):
        raise FramingError("sample_rate_hz must fit in uint32")

    header = struct.pack(
        HEADER_FMT,
        MAGIC,
        VERSION,
        MSG_HEARTBEAT,
        node_id,
        seq,
        t_node_us,
        sample_rate_hz,
        0,  # channel_count
        0,  # sample_count
    )
    crc = crc16_ccitt_false(header)
    return header + struct.pack("<H", crc)


def frame_length(channel_count: int, sample_count: int) -> int:
    """Total on-wire length for a block of the given shape (header + payload + CRC)."""
    return HEADER_SIZE + sample_count * channel_count * 2 + CRC_SIZE


def decode(frame: bytes) -> Packet:
    """Decode and fully validate one frame; return a :class:`Packet`.

    Raises :class:`FramingError` on bad magic/version/msg_type/length and
    :class:`CrcError` on a CRC mismatch. The Receiver relies on these being distinct
    so it can count corruption separately from garbage.
    """
    if len(frame) < HEADER_SIZE + CRC_SIZE:
        raise FramingError(f"frame too short: {len(frame)} bytes")
    if len(frame) > MAX_PACKET_BYTES:
        raise FramingError(f"frame exceeds MAX_PACKET_BYTES: {len(frame)} bytes")

    (magic, version, msg_type, node_id, seq, t_node_us,
     sample_rate_hz, channel_count, sample_count) = struct.unpack(
        HEADER_FMT, frame[:HEADER_SIZE]
    )

    if magic != MAGIC:
        raise FramingError(f"bad magic: {magic!r}")
    if version != VERSION:
        raise FramingError(f"unsupported version: {version}")
    if msg_type not in _DECODABLE_MSG_TYPES:
        raise FramingError(f"unsupported msg_type: {msg_type}")

    expected_len = frame_length(channel_count, sample_count)
    if len(frame) != expected_len:
        raise FramingError(
            f"length mismatch: header implies {expected_len} bytes, got {len(frame)}"
        )

    found_crc = struct.unpack("<H", frame[-CRC_SIZE:])[0]
    computed_crc = crc16_ccitt_false(frame[:-CRC_SIZE])
    if found_crc != computed_crc:
        raise CrcError(expected=computed_crc, found=found_crc)

    payload = frame[HEADER_SIZE:-CRC_SIZE]
    samples: List[List[int]] = []
    row_bytes = channel_count * 2
    for s in range(sample_count):
        row = list(struct.unpack(
            "<" + "h" * channel_count, payload[s * row_bytes:(s + 1) * row_bytes]
        ))
        samples.append(row)

    return Packet(
        node_id=node_id,
        seq=seq,
        t_node_us=t_node_us,
        sample_rate_hz=sample_rate_hz,
        channel_count=channel_count,
        samples=samples,
        msg_type=msg_type,
    )


def decode_frame(frame: bytes) -> dict:
    """Decode a frame to the canonical golden-vector ``input`` dict.

    Convenience wrapper used by the vector round-trip test:
    ``decode_frame(bytes.fromhex(v["frame_hex"])) == v["input"]``.
    """
    return decode(frame).to_input()
