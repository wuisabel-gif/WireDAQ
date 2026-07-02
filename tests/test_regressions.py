"""
Regression guards for five bugs that shipped in untested gaps.

Each test fails against the pre-fix code and passes after. Kept together because they
share one root theme: features (heartbeats, clock drift, corruption stats) whose happy
path was tested but whose real behavior was not.

    python3 tests/test_regressions.py
    pytest tests/test_regressions.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiredaq.protocol.codec import (  # noqa: E402
    CrcError,
    FramingError,
    MSG_HEARTBEAT,
    decode,
    encode_heartbeat,
    encode_sample_block,
)
from wiredaq.ground_station.logger.raw_logger import (  # noqa: E402
    RawFrameLogger,
    read_raw_log,
)
from wiredaq.ground_station.receiver import StreamReceiver  # noqa: E402
from wiredaq.daq_sim.nodes.synthetic_node import SyntheticNode  # noqa: E402
from wiredaq.daq_sim.transports.in_process import InProcessTransport  # noqa: E402
from wiredaq.daq_sim.transports.impairment_transport import (  # noqa: E402
    ImpairmentConfig,
    ImpairmentTransport,
)


class _OneShotByteStream:
    """A ByteStreamTransport that hands over a fixed buffer once, then EOFs."""

    def __init__(self, data):
        self._data = data

    def recv(self):
        data, self._data = self._data, b""
        return data

    def close(self):
        pass


def test_raw_logger_archives_heartbeat_byte_identical(tmp_path):
    # Bug 1: the logger re-encoded every packet as a SAMPLE_BLOCK, so a heartbeat came
    # back with msg_type=1 and an empty payload instead of its original bytes.
    hb = encode_heartbeat(node_id=3, seq=9, t_node_us=1234, sample_rate_hz=3200)
    path = tmp_path / "hb.wdlog"
    logger = RawFrameLogger(str(path))
    logger.consume(decode(hb))
    logger.close()
    assert list(read_raw_log(str(path))) == [hb]


def test_stream_receiver_frames_heartbeat():
    # Bug 2: StreamReceiver only accepted SAMPLE_BLOCK, so every heartbeat was shredded
    # into resync_bytes and its seq showed up as phantom loss downstream.
    hb = encode_heartbeat(node_id=1, seq=0, t_node_us=5, sample_rate_hz=3200)
    receiver = StreamReceiver(_OneShotByteStream(hb))
    packets = list(receiver.packets())
    assert [p.msg_type for p in packets] == [MSG_HEARTBEAT]
    assert receiver.stats.resync_bytes == 0


def test_drift_ppm_actually_diverges():
    # Bug 3: rounding each block's increment quantized away any drift < 0.5 us/block, so
    # the CLI-default ppm values produced exactly zero divergence.
    a = SyntheticNode(node_id=0, drift_ppm=0.0, max_packets=1000)
    b = SyntheticNode(node_id=1, drift_ppm=100.0, max_packets=1000)
    for _ in range(1000):
        a.next_frame()
        b.next_frame()
    assert b._t_now_us > a._t_now_us  # 100 ppm over 1000 blocks is a visible offset


def test_corruption_is_always_crc_not_framing():
    # Bug 5: corrupting a header-only heartbeat could hit version/msg_type/length, so it
    # was rejected as a framing error and miscounted instead of as CRC corruption.
    hb = encode_heartbeat(node_id=1, seq=0, t_node_us=5, sample_rate_hz=3200)
    sb = encode_sample_block(
        node_id=1, seq=1, t_node_us=5, sample_rate_hz=3200, channel_count=1, samples=[[3]]
    )
    for base in (hb, sb):
        for seed in range(200):
            link = ImpairmentTransport(
                InProcessTransport(), ImpairmentConfig(corrupt=1.0), seed=seed
            )
            link.send(base)
            got = link.inner.recv()
            try:
                decode(got)
            except CrcError:
                pass
            except FramingError:
                raise AssertionError(f"corruption surfaced as FramingError (seed={seed})")
            else:
                raise AssertionError("corruption was not caught at all")


# Bug 4 (C++ uint8 sample_count overflow) is guarded on the C++ side; there is no Python
# analogue because encode_sample_block validates sample_count against 0xFF directly.


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_raw_logger_archives_heartbeat_byte_identical(Path(d))
    test_stream_receiver_frames_heartbeat()
    test_drift_ppm_actually_diverges()
    test_corruption_is_always_crc_not_framing()
    print("all regression guards pass")
