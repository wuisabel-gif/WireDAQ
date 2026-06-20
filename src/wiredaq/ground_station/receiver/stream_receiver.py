"""
StreamReceiver — frame a WireDAQ packet stream out of a raw byte stream.

This is the receiver for serial / RS-485 links (and any :class:`ByteStreamTransport`),
and the piece that does the work the datagram :class:`FrameReceiver` gets for free: it
finds frame boundaries itself. Like ``FrameReceiver`` it satisfies the :class:`Receiver`
port and yields the same :class:`Packet` objects, so the Collector is identical either
way — the architecture's promise that swapping the transport is a wiring change, not a
rewrite, demonstrated across the datagram/stream divide.

The framing loop:

1. Scan the buffer for the magic sync word ``57 44``. Bytes before it are line noise —
   discard them and count them as ``resync_bytes``.
2. With magic at the front, read the 24-byte header. If the version / msg_type are wrong
   or the implied length is impossible, this magic was a coincidence in the noise: drop
   one byte and rescan.
3. Once the whole frame is buffered, validate + decode it. A good frame is yielded and
   consumed; a frame that fails CRC is counted (``crc_errors``) and skipped — its header
   was well-formed, so we trust its length and step past the whole frame.
4. A partial header or partial frame just means "need more bytes" — stop and wait for the
   next read.

This is single-pass and incremental: feed it bytes in any chunking, including a frame
split across many reads, and it reassembles correctly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from wiredaq.protocol.codec import (
    CRC_SIZE,
    HEADER_SIZE,
    MAGIC,
    MAX_PACKET_BYTES,
    MSG_SAMPLE_BLOCK,
    VERSION,
    CrcError,
    FramingError,
    Packet,
    decode,
)
from wiredaq.daq_sim.core.interfaces import ByteStreamTransport, Receiver

_VERSION_OFFSET = 2
_MSGTYPE_OFFSET = 3
_CHANNEL_COUNT_OFFSET = 22
_SAMPLE_COUNT_OFFSET = 23


@dataclass
class StreamReceiverStats:
    received: int = 0        # valid packets decoded and yielded
    crc_errors: int = 0      # well-framed packets rejected by the CRC check (corruption)
    framing_errors: int = 0  # frames that parsed structurally but decode still rejected
    resync_bytes: int = 0    # bytes discarded as line noise / false sync words


class StreamReceiver(Receiver):
    """Reassembles and validates frames pulled from a byte-stream transport."""

    def __init__(self, transport: ByteStreamTransport) -> None:
        self.transport = transport
        self.stats = StreamReceiverStats()
        self._buf = bytearray()

    def _fill(self) -> None:
        """Pull every byte currently available from the transport into the buffer."""
        while True:
            chunk = self.transport.recv()
            if not chunk:
                return
            self._buf += chunk

    def packets(self) -> Iterator[Packet]:
        self._fill()
        buf = self._buf

        while True:
            idx = buf.find(MAGIC)
            if idx == -1:
                # No sync word in the buffer. Keep a trailing byte only if it could be
                # the first half of a sync word split across reads; discard the rest.
                if buf and buf[-1] == MAGIC[0]:
                    self.stats.resync_bytes += len(buf) - 1
                    del buf[:-1]
                else:
                    self.stats.resync_bytes += len(buf)
                    del buf[:]
                return

            if idx > 0:
                # Line noise before the sync word.
                self.stats.resync_bytes += idx
                del buf[:idx]

            if len(buf) < HEADER_SIZE:
                return  # have the sync word, need the rest of the header

            version = buf[_VERSION_OFFSET]
            msg_type = buf[_MSGTYPE_OFFSET]
            channel_count = buf[_CHANNEL_COUNT_OFFSET]
            sample_count = buf[_SAMPLE_COUNT_OFFSET]

            if version != VERSION or msg_type != MSG_SAMPLE_BLOCK:
                # A sync word that wasn't really a frame header — false positive.
                self.stats.resync_bytes += 1
                del buf[:1]
                continue

            frame_len = HEADER_SIZE + sample_count * channel_count * 2 + CRC_SIZE
            if frame_len > MAX_PACKET_BYTES:
                self.stats.resync_bytes += 1
                del buf[:1]
                continue

            if len(buf) < frame_len:
                return  # whole frame not here yet

            candidate = bytes(buf[:frame_len])
            try:
                packet = decode(candidate)
            except CrcError:
                # Header was well-formed; trust its length and step past the bad frame.
                self.stats.crc_errors += 1
                del buf[:frame_len]
                continue
            except FramingError:
                self.stats.framing_errors += 1
                self.stats.resync_bytes += 1
                del buf[:1]
                continue

            self.stats.received += 1
            del buf[:frame_len]
            yield packet
