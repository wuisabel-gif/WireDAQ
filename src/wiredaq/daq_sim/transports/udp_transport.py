"""
UdpTransport — a real UDP datagram link (Phase 3, "real link").

Unlike the in-process and serial transports, this one genuinely traverses the operating
system's network stack: bytes are sent with ``sendto`` and read with ``recvfrom`` over
real UDP sockets on the loopback interface. It satisfies the datagram :class:`Transport`
port (UDP preserves message boundaries — one ``send`` is one ``recv``), so it composes
with everything already built: ``ImpairmentTransport`` can wrap it, ``FrameReceiver``
reads from it, and the ``Collector`` is none the wiser.

A single :class:`UdpTransport` instance models one end-to-end link: ``send`` transmits
from a TX socket to the bound RX socket, and ``recv`` reads whatever datagrams have
arrived. Reads are non-blocking and return ``None`` when nothing is queued, matching the
port's contract.
"""

from __future__ import annotations

import socket
from typing import Optional, Tuple

from wiredaq.daq_sim.core.interfaces import Transport

# WireDAQ frames are capped at 256 bytes; a 2 KiB read buffer is comfortably larger than
# any single datagram, so recvfrom never truncates a frame.
_RECV_BUFSIZE = 2048


class UdpTransport(Transport):
    """A loopback UDP link: send transmits a datagram, recv reads one (or None)."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        rcvbuf: int = 1 << 20,
    ) -> None:
        # RX socket: bound, non-blocking, generously buffered so bursts aren't dropped
        # by the kernel before the collector drains them.
        self._rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        except OSError:
            pass  # best-effort; not all platforms honor large buffers
        self._rx.bind((host, port))
        self._rx.setblocking(False)
        self.rx_addr: Tuple[str, int] = self._rx.getsockname()

        # TX socket: unbound, just used to send to the RX address.
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, frame: bytes) -> None:
        self._tx.sendto(bytes(frame), self.rx_addr)

    def recv(self) -> Optional[bytes]:
        try:
            data, _addr = self._rx.recvfrom(_RECV_BUFSIZE)
        except BlockingIOError:
            return None
        return data

    def close(self) -> None:
        self._tx.close()
        self._rx.close()
