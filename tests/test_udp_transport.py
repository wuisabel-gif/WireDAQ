"""
UdpTransport tests — frames over a real loopback UDP socket.

These actually traverse the OS network stack (sendto/recvfrom on 127.0.0.1), proving the
datagram port works against real sockets and composes with the impairment decorator, the
shared receiver, and the collector exactly like the in-process transport.

    python3 tests/test_udp_transport.py
    pytest tests/test_udp_transport.py
"""

import select
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiredaq.ground_station.receiver import FrameReceiver  # noqa: E402
from wiredaq.protocol.codec import decode  # noqa: E402
from wiredaq.daq_sim.collector.collector import Collector  # noqa: E402
from wiredaq.daq_sim.nodes.synthetic_node import SyntheticNode  # noqa: E402
from wiredaq.daq_sim.transports.impairment_transport import (  # noqa: E402
    ImpairmentConfig,
    ImpairmentTransport,
)
from wiredaq.daq_sim.transports.udp_transport import UdpTransport  # noqa: E402


def _drain(rx_sock, receiver, expected, timeout=3.0):
    """Pull packets until `expected` have arrived or the timeout elapses, waiting on the
    socket with select so the test is robust to scheduling, not racy."""
    got = []
    end = time.monotonic() + timeout
    while len(got) < expected and time.monotonic() < end:
        select.select([rx_sock], [], [], 0.05)
        got.extend(receiver.packets())
    return got


def test_udp_round_trip_in_order():
    frames = list(SyntheticNode(node_id=1, max_packets=30).frames())
    transport = UdpTransport()
    try:
        receiver = FrameReceiver(transport)
        for f in frames:
            transport.send(f)
        got = _drain(transport._rx, receiver, expected=30)
    finally:
        transport.close()

    assert len(got) == 30
    assert [p.seq for p in got] == list(range(30))   # loopback preserves order
    assert got == [decode(f) for f in frames]         # bit-identical
    assert receiver.stats.crc_errors == 0
    assert receiver.stats.framing_errors == 0


def test_impairment_over_real_udp():
    # ImpairmentTransport(UdpTransport(...)) — drop ~30% before they hit the wire; the
    # collector must detect the loss from the sequence field on the surviving stream.
    inner = UdpTransport()
    transport = ImpairmentTransport(inner, ImpairmentConfig(loss=0.3), seed=11)
    try:
        receiver = FrameReceiver(transport)
        metrics_collector = Collector(receiver, [])
        node = SyntheticNode(node_id=1, max_packets=120)

        # Interleave send + drain so the kernel buffer never overflows.
        for f in node.frames():
            transport.send(f)
            metrics_collector.run()
        _drain(inner._rx, receiver, expected=10**9, timeout=0.5)  # final flush
        metrics_collector.run()
    finally:
        transport.close()

    assert transport.stats.dropped > 0
    # Everything the link actually delivered was received (loopback is lossless).
    assert receiver.stats.received == transport.stats.delivered
    ns = metrics_collector.stats.nodes[1]
    assert ns.lost > 0
    assert ns.lost <= transport.stats.dropped


def _run_standalone():
    tests = [test_udp_round_trip_in_order, test_impairment_over_real_udp]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"All {len(tests)} UDP checks passed.")


if __name__ == "__main__":
    _run_standalone()
