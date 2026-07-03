"""
SerialPortTransport — the hardware-in-the-loop seam (Phase 4).

A real sensor board on a UART/USB-serial link *is* a :class:`ByteStreamTransport`: it emits
an unframed byte stream that the existing :class:`StreamReceiver` already knows how to frame
(sync word, header length, CRC, resync past noise). So bringing up real hardware is not a
rewrite — it is swapping the simulated ``SerialTransport`` for this one behind the same port.
Every stage downstream (StreamReceiver → Collector → sinks) is the exact code exercised in
software, which is the whole point of "wire-ready".

This adapter is deliberately dependency-light and testable without hardware: it reads from
any object exposing ``read(n) -> bytes`` (pyserial's ``Serial``, a file object, or an
in-memory fake). Use :func:`open_serial_port` to get a configured pyserial port for a real
device; that is the only place ``pyserial`` (an optional extra) is touched, and it is
imported lazily so this module imports with the standard library alone.

    # against real hardware (pip install "wiredaq[hardware]"):
    port = open_serial_port("/dev/tty.usbmodem1101", baudrate=115200)
    transport = SerialPortTransport(port)
    receiver = StreamReceiver(transport)
    collector = Collector(receiver, [MetricsSink()], clock=WallClock())
    while running:
        collector.run()   # frames real bytes with the same code the sim used
"""

from __future__ import annotations

from typing import Protocol

from wiredaq.daq_sim.core.interfaces import ByteStreamTransport


class BytePort(Protocol):
    """The slice of a serial port this adapter needs — pyserial's ``Serial`` satisfies it."""

    def read(self, size: int) -> bytes: ...


class SerialPortTransport(ByteStreamTransport):
    """A receive-side byte-stream transport backed by a real (or fake) serial port.

    ``recv`` returns whatever bytes are currently available, up to ``max_read`` (a stand-in
    for the UART FIFO depth), or ``b""`` if none — the :class:`ByteStreamTransport` contract.
    The port must be opened non-blocking (``timeout=0`` for pyserial) so ``read`` returns
    immediately with the bytes on hand instead of waiting for a full ``max_read``.
    """

    def __init__(self, port: BytePort, max_read: int = 256) -> None:
        if max_read < 1:
            raise ValueError("max_read must be >= 1")
        self.port = port
        self.max_read = max_read

    def send(self, data: bytes) -> None:
        # A sensor board is a source only; the ground station does not push bytes back to it
        # on this path. (Downlink/commanding would be a separate control-plane concern.)
        raise NotImplementedError("SerialPortTransport is receive-only")

    def recv(self) -> bytes:
        return self.port.read(self.max_read) or b""

    def close(self) -> None:
        closer = getattr(self.port, "close", None)
        if callable(closer):
            closer()


def open_serial_port(device: str, baudrate: int = 115200, timeout: float = 0.0):
    """Open a real serial device for use with :class:`SerialPortTransport`.

    Lazily imports ``pyserial`` (the optional ``hardware`` extra: ``pip install
    "wiredaq[hardware]"``). ``timeout=0`` makes reads non-blocking, matching ``recv``'s
    "return whatever is available" contract.
    """
    try:
        import serial  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without pyserial
        raise ModuleNotFoundError(
            "reading a real serial device needs pyserial; install it with "
            "`pip install \"wiredaq[hardware]\"`"
        ) from exc
    return serial.Serial(device, baudrate=baudrate, timeout=timeout)
