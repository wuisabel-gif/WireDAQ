"""
WireDAQ core ports — the stable interfaces of the hexagonal architecture.

These four ABCs are the *seams* the whole project is built around (see
``docs/adr/0001-wire-ready-architecture.md``). Everything else in the tree is an
**adapter** behind one of these ports, and the :class:`Collector` depends only on the
ports — never on a concrete adapter. A "phase" is a different choice of adapters wired
together, not a change to anything in this file.

  SensorNode  — produces framed wire bytes        (synthetic now, real board later)
  Transport   — moves opaque framed bytes          (in-process now, UDP/serial later)
  Receiver    — validates bytes, yields Packets     (one impl, shared with ground station)
  Sink        — consumes decoded Packets            (CSV log, metrics, dashboard, ...)

The currency that flows across the seams is bytes on the wire (Transport) and decoded
:class:`~protocol.codec.Packet` objects (Receiver → Collector → Sink).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, Optional

from protocol.codec import Packet

# Re-export so adapters can `from ...core.interfaces import Packet` without reaching
# across to the protocol package directly.
__all__ = [
    "Packet",
    "SensorNode",
    "Transport",
    "ByteStreamTransport",
    "Receiver",
    "Sink",
]


class SensorNode(ABC):
    """A source of framed sample packets.

    In a real deployment this is a sensor board emitting WireDAQ frames over a link; in
    the simulator it is a synthetic generator. Either way it produces complete on-wire
    frames (encoded against ``packet_schema.yaml``), so everything downstream is
    identical whether the bytes are synthetic or real — the point of the architecture.
    """

    node_id: int

    @abstractmethod
    def next_frame(self) -> Optional[bytes]:
        """Return the next complete on-wire frame, or ``None`` when the node is done."""

    def frames(self) -> Iterator[bytes]:
        """Iterate frames until the node is exhausted."""
        while True:
            frame = self.next_frame()
            if frame is None:
                return
            yield frame


class Transport(ABC):
    """Moves opaque, already-framed bytes from a sender to a receiver.

    This port is datagram-oriented: one :meth:`send` carries one frame, one
    :meth:`recv` returns one frame (or ``None`` when nothing is queued). Packet loss,
    reordering, duplication, and delay therefore act on whole frames — exactly what a
    real UDP or serial link does to packets — which is why ``ImpairmentTransport`` can
    decorate any Transport without the Collector noticing.
    """

    @abstractmethod
    def send(self, frame: bytes) -> None:
        """Hand one framed packet to the link."""

    @abstractmethod
    def recv(self) -> Optional[bytes]:
        """Return the next available frame, or ``None`` if none is ready."""

    def close(self) -> None:  # noqa: B027 - optional hook, default no-op
        """Release any resources / flush buffers. Default: nothing to do."""


class ByteStreamTransport(ABC):
    """Moves an opaque, unframed **byte stream** — no message boundaries preserved.

    This is what a real serial line (UART / RS-485) is: bytes in, bytes out, and the
    receiver must find frame boundaries itself using the magic sync word and the header's
    length fields. A read returns whatever bytes happen to be available — possibly a
    partial frame, possibly several frames, possibly nothing. ``SerialTransport`` adapters
    implement this port; the :class:`StreamReceiver` does the framing.

    Contrast with :class:`Transport`, which is datagram-oriented (UDP, in-process) and
    preserves one-send-one-recv boundaries. Both feed a :class:`Receiver` that yields the
    same :class:`Packet` objects, so the Collector neither knows nor cares which it is.
    """

    @abstractmethod
    def send(self, data: bytes) -> None:
        """Push bytes onto the wire (no framing implied)."""

    @abstractmethod
    def recv(self) -> bytes:
        """Return whatever bytes are currently available, or ``b''`` if none."""

    def close(self) -> None:  # noqa: B027 - optional hook, default no-op
        """Release any resources / flush buffers. Default: nothing to do."""


class Receiver(ABC):
    """Reads bytes off a Transport, validates them, and yields decoded Packets.

    One implementation is shared between the simulator and the real ground station — so
    the validation, CRC checking, and framing exercised in Phase 1 are the same code
    that runs against real hardware in Phase 3+. Invalid frames are dropped and counted,
    never yielded.
    """

    @abstractmethod
    def packets(self) -> Iterator[Packet]:
        """Yield every valid decoded packet currently available from the transport."""


class Sink(ABC):
    """Consumes decoded packets. The terminal stage of the pipeline.

    Adapters: a CSV/binary logger, a metrics aggregator, a live dashboard feed. A Sink
    must not assume where a packet came from.
    """

    @abstractmethod
    def consume(self, packet: Packet) -> None:
        """Process one decoded packet."""

    def close(self) -> None:  # noqa: B027 - optional hook, default no-op
        """Flush and release resources. Default: nothing to do."""
