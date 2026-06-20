"""
RawFrameLogger — the ground station's archival sink.

Where ``CsvLogger`` writes a human-readable, analysis-friendly table, this writes the
**exact wire bytes** of every packet to a length-prefixed binary log, so a capture can be
replayed bit-for-bit later (see :class:`~tools.daq_sim.nodes.replay_node.ReplayNode`).
This is the forensic record a real ground station keeps: the ground truth of what came
off the link.

A subtle but load-bearing point: a :class:`Sink` receives *decoded* packets, not raw
bytes — but re-encoding a decoded packet with the production codec reproduces the
original frame exactly, because the codec round-trips the golden vectors by construction.
So the archive is byte-identical to what was received, with no separate "raw bytes" path
needed.

Log format (repeated): ``uint16 little-endian frame length`` followed by that many bytes.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO, Iterator, Optional

from protocol.codec import Packet, encode_sample_block
from tools.daq_sim.core.interfaces import Sink

_LEN_FMT = "<H"  # 2-byte little-endian length prefix
_LEN_SIZE = 2


class RawFrameLogger(Sink):
    """Append each packet's exact wire frame to a length-prefixed binary log."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: Optional[BinaryIO] = self.path.open("wb")
        self.frames_written = 0
        self.bytes_written = 0

    def consume(self, packet: Packet) -> None:
        if self._fh is None:
            raise RuntimeError("RawFrameLogger is closed")
        frame = encode_sample_block(**packet.to_input())  # round-trips to original bytes
        self._fh.write(struct.pack(_LEN_FMT, len(frame)))
        self._fh.write(frame)
        self.frames_written += 1
        self.bytes_written += _LEN_SIZE + len(frame)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def read_raw_log(path: str) -> Iterator[bytes]:
    """Yield each raw frame from a log written by :class:`RawFrameLogger`."""
    data = Path(path).read_bytes()
    pos = 0
    while pos + _LEN_SIZE <= len(data):
        (length,) = struct.unpack_from(_LEN_FMT, data, pos)
        pos += _LEN_SIZE
        if pos + length > len(data):
            raise ValueError("truncated raw log: length prefix exceeds remaining bytes")
        yield data[pos:pos + length]
        pos += length
    if pos != len(data):
        raise ValueError("trailing bytes in raw log (not a clean frame boundary)")
