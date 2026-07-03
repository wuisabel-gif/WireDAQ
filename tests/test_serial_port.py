"""
Hardware-in-the-loop seam, verified without hardware (Phase 4).

A real sensor board would feed bytes into :class:`SerialPortTransport`; here a fake port
(same ``read(n)`` interface pyserial exposes) replays a byte stream shaped like what a
board emits — framed samples with inter-frame line noise, delivered in small chunks. The
point: the frames come back out through the *unchanged* StreamReceiver → Collector, which
is exactly the ground-station code that will run against the real board. What this cannot
prove — on-target codec bytes, real crystal drift, real link timing — is what the bring-up
log (docs/bring-up-log-template.md) captures once a board is attached.

    python3 tests/test_serial_port.py
    pytest tests/test_serial_port.py
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiredaq.daq_sim.collector.collector import Collector  # noqa: E402
from wiredaq.daq_sim.nodes.synthetic_node import SyntheticNode  # noqa: E402
from wiredaq.daq_sim.transports.serial_port import SerialPortTransport  # noqa: E402
from wiredaq.ground_station.receiver import StreamReceiver  # noqa: E402


class FakePort:
    """A stand-in for a pyserial port: ``read(n)`` returns up to n available bytes."""

    def __init__(self, data: bytes) -> None:
        self._buf = bytearray(data)
        self.closed = False

    def read(self, size: int) -> bytes:
        out = bytes(self._buf[:size])
        del self._buf[:size]
        return out

    def close(self) -> None:
        self.closed = True


def _board_byte_stream(node, seed=0):
    """Concatenate a node's frames with random inter-frame line noise, like a real UART."""
    rng = random.Random(seed)
    stream = bytearray()
    count = 0
    for frame in node.frames():
        stream += bytes(rng.randrange(256) for _ in range(rng.randint(0, 6)))  # noise gap
        stream += frame
        count += 1
    return bytes(stream), count


def test_hil_path_recovers_frames_without_hardware():
    node = SyntheticNode(node_id=5, max_packets=25, seed=1, drift_ppm=40)
    stream, sent = _board_byte_stream(node, seed=3)

    port = FakePort(stream)
    transport = SerialPortTransport(port, max_read=8)  # tiny FIFO → frames span reads
    collector = Collector(StreamReceiver(transport), sinks=[])

    prev = -1
    while collector.stats.total_packets != prev:  # drain until quiet
        prev = collector.stats.total_packets
        collector.run()

    ns = collector.stats.nodes[5]
    assert ns.packets == sent  # every framed packet recovered from the noisy byte stream
    assert ns.lost == 0
    transport.close()
    assert port.closed


def test_transport_is_receive_only():
    port = FakePort(b"")
    transport = SerialPortTransport(port)
    try:
        transport.send(b"x")
    except NotImplementedError:
        pass
    else:
        raise AssertionError("SerialPortTransport.send should be receive-only")


if __name__ == "__main__":
    test_hil_path_recovers_frames_without_hardware()
    test_transport_is_receive_only()
    print("HIL serial-port path: all checks pass")
