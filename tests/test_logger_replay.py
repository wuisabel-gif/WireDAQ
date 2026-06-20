"""
Record/replay fidelity — RawFrameLogger ↔ ReplayNode.

Log a session's exact wire bytes, replay it back through the pipeline, and confirm the
replayed packets are identical to the originals. This is the regression-oracle property:
a captured session reproduces deterministically. It also exercises the codec round-trip
(the logger re-encodes decoded packets and must get the original bytes back).

    python3 tests/test_logger_replay.py
    pytest tests/test_logger_replay.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ground_station.logger import RawFrameLogger, read_raw_log  # noqa: E402
from ground_station.receiver import FrameReceiver  # noqa: E402
from protocol.codec import decode  # noqa: E402
from tools.daq_sim.collector.collector import Collector  # noqa: E402
from tools.daq_sim.nodes.replay_node import ReplayNode  # noqa: E402
from tools.daq_sim.nodes.synthetic_node import SyntheticNode  # noqa: E402
from tools.daq_sim.sinks.metrics import MetricsSink  # noqa: E402
from tools.daq_sim.transports.in_process import InProcessTransport  # noqa: E402


def _capture(frames, path):
    """Run frames through a collector with a RawFrameLogger and return the originals."""
    transport = InProcessTransport()
    receiver = FrameReceiver(transport)
    logger = RawFrameLogger(path)
    collector = Collector(receiver, [logger])
    for f in frames:
        transport.send(f)
    collector.run()
    collector.close()
    return logger


def test_raw_log_is_byte_identical():
    frames = list(SyntheticNode(node_id=3, max_packets=25, seed=4).frames())
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "capture.wdlog")
        logger = _capture(frames, path)
        assert logger.frames_written == 25
        # The archived frames equal the original wire bytes, exactly.
        assert list(read_raw_log(path)) == frames


def test_replay_reproduces_packets():
    originals = list(SyntheticNode(node_id=3, max_packets=40, seed=4).frames())
    decoded_originals = [decode(f) for f in originals]

    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "capture.wdlog")
        _capture(originals, path)

        # Replay the capture as a live source through a fresh pipeline.
        node = ReplayNode(path, node_id=99)
        assert len(node) == 40
        transport = InProcessTransport()
        receiver = FrameReceiver(transport)
        metrics = MetricsSink()
        collector = Collector(receiver, [metrics])

        replayed = []
        for frame in node.frames():
            transport.send(frame)
        for pkt in receiver.packets():
            replayed.append(pkt)
            collector.process(pkt)

    assert replayed == decoded_originals
    assert metrics.packets == 40
    assert collector.stats.nodes[3].lost == 0  # a clean capture replays loss-free


def _run_standalone():
    tests = [test_raw_log_is_byte_identical, test_replay_reproduces_packets]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"All {len(tests)} logger/replay checks passed.")


if __name__ == "__main__":
    _run_standalone()
