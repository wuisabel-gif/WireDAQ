"""WireDAQ production codec — see :mod:`protocol.codec.wiredaq_codec`."""

from protocol.codec.wiredaq_codec import (  # noqa: F401
    CRC_SIZE,
    HEADER_SIZE,
    MAGIC,
    MAX_PACKET_BYTES,
    MSG_SAMPLE_BLOCK,
    VERSION,
    CodecError,
    CrcError,
    FramingError,
    Packet,
    crc16_ccitt_false,
    decode,
    decode_frame,
    encode_sample_block,
    frame_length,
)

__all__ = [
    "MAGIC",
    "VERSION",
    "MSG_SAMPLE_BLOCK",
    "MAX_PACKET_BYTES",
    "HEADER_SIZE",
    "CRC_SIZE",
    "Packet",
    "CodecError",
    "FramingError",
    "CrcError",
    "crc16_ccitt_false",
    "encode_sample_block",
    "decode",
    "decode_frame",
    "frame_length",
]
