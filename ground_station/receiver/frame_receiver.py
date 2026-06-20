"""
FrameReceiver — the shared receiver (ADR 0001 build step 6).

Reads frames off a :class:`Transport`, validates and decodes each one with the
production codec, and yields :class:`Packet` objects. The *same* receiver runs in the
simulator and in the real ground station — so the CRC checking and validation proven in
Phase 1 are exactly what guards real hardware in Phase 3+.

Invalid frames are dropped and counted, never yielded:

* a bad CRC is counted as ``crc_errors`` (corruption a real link would cause), and
* anything that isn't a well-formed WireDAQ frame is counted as ``framing_errors``.

This receiver is datagram-oriented: one frame per ``recv``, so framing is trivial. For a
raw serial *byte stream*, where boundaries must be found via the magic sync word, use
:class:`~ground_station.receiver.stream_receiver.StreamReceiver` instead — it satisfies
the same :class:`Receiver` port and yields the same packets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from protocol.codec import CrcError, FramingError, Packet, decode
from tools.daq_sim.core.interfaces import Receiver, Transport


@dataclass
class ReceiverStats:
    received: int = 0        # valid packets decoded and yielded
    crc_errors: int = 0      # frames rejected by the CRC check (corruption)
    framing_errors: int = 0  # frames that weren't valid WireDAQ frames at all


class FrameReceiver(Receiver):
    """Validates and decodes frames pulled from a transport."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self.stats = ReceiverStats()

    def packets(self) -> Iterator[Packet]:
        """Drain the transport, yielding every valid packet currently available."""
        while True:
            frame = self.transport.recv()
            if frame is None:
                return
            try:
                packet = decode(frame)
            except CrcError:
                self.stats.crc_errors += 1
                continue
            except FramingError:
                self.stats.framing_errors += 1
                continue
            self.stats.received += 1
            yield packet
