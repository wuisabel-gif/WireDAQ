"""
End-to-end pipeline tests over the honest-fake transport.

Because all randomness is seeded, the impairment pattern is exactly reproducible, so we
can assert that the impairment the transport *injected* equals what the receiver and
collector *observed*. That equivalence is the proof the seams line up.

    python3 tests/test_pipeline.py
    pytest tests/test_pipeline.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ground_station.receiver import FrameReceiver  # noqa: E402
from tools.daq_sim.collector.collector import Collector, seq_delta  # noqa: E402
from tools.daq_sim.nodes.synthetic_node import SyntheticNode  # noqa: E402
from tools.daq_sim.sinks.metrics import MetricsSink  # noqa: E402
from tools.daq_sim.transports.impairment_transport import (  # noqa: E402
    ImpairmentConfig,
    ImpairmentTransport,
)
from tools.daq_sim.transports.in_process import InProcessTransport  # noqa: E402


def _run(config, packets=300, seed=3, node_id=1):
    node = SyntheticNode(node_id=node_id, max_packets=packets, seed=seed)
    transport = ImpairmentTransport(InProcessTransport(), config, seed=seed)
    receiver = FrameReceiver(transport)
    metrics = MetricsSink()
    collector = Collector(receiver, [metrics])
    for frame in node.frames():
        transport.send(frame)
    transport.close()
    collector.run()
    return transport, receiver, collector, metrics


def test_perfect_link_is_lossless():
    transport, receiver, collector, metrics = _run(ImpairmentConfig(), packets=200)
    assert transport.stats.dropped == 0
    assert receiver.stats.crc_errors == 0
    assert receiver.stats.framing_errors == 0
    assert receiver.stats.received == 200
    assert metrics.packets == 200
    node_stats = collector.stats.nodes[1]
    assert node_stats.lost == 0
    assert node_stats.reordered == 0
    assert node_stats.duplicated == 0


def test_corruption_is_caught_by_crc():
    # Heavy corruption, nothing else: every corrupted frame must be rejected by CRC,
    # never silently accepted as good data.
    transport, receiver, collector, metrics = _run(
        ImpairmentConfig(corrupt=0.5), packets=400
    )
    assert transport.stats.corrupted > 0
    assert receiver.stats.crc_errors == transport.stats.corrupted
    # Everything the receiver accepted was uncorrupted.
    assert receiver.stats.received == transport.stats.delivered - transport.stats.corrupted


def test_loss_is_detected_from_sequence():
    transport, receiver, collector, metrics = _run(
        ImpairmentConfig(loss=0.2), packets=500
    )
    ns = collector.stats.nodes[1]
    # Frames the link dropped (minus any at the very tail, which leave no forward gap to
    # observe) must show up as detected loss.
    assert transport.stats.dropped > 0
    assert ns.lost > 0
    # Detected loss can never exceed what was actually dropped.
    assert ns.lost <= transport.stats.dropped
    # Accepted + lost accounts for every packet that reached the high-water mark.
    assert ns.packets + ns.lost == ns.last_seq - ns.first_seq + 1


def test_duplicates_are_detected():
    transport, receiver, collector, metrics = _run(
        ImpairmentConfig(duplicate=0.3), packets=400
    )
    ns = collector.stats.nodes[1]
    assert transport.stats.duplicated > 0
    assert ns.duplicated == transport.stats.duplicated


def test_seq_delta_wraps():
    assert seq_delta(0, 0xFFFFFFFF) == 1          # wrap forward
    assert seq_delta(0xFFFFFFFF, 0) == -1         # wrap backward
    assert seq_delta(10, 5) == 5
    assert seq_delta(5, 10) == -5


def _run_standalone():
    tests = [
        test_perfect_link_is_lossless,
        test_corruption_is_caught_by_crc,
        test_loss_is_detected_from_sequence,
        test_duplicates_are_detected,
        test_seq_delta_wraps,
    ]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"All {len(tests)} pipeline checks passed.")


if __name__ == "__main__":
    _run_standalone()
