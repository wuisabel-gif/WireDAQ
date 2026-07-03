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

import struct  # noqa: E402

from wiredaq.protocol.codec import (  # noqa: E402
    CrcError,
    FramingError,
    MAGIC,
    MSG_HEARTBEAT,
    VERSION,
    crc16_ccitt_false,
    decode,
    encode_heartbeat,
    encode_sample_block,
)
from wiredaq.protocol.codec.wiredaq_codec import HEADER_FMT  # noqa: E402
from wiredaq.daq_sim.collector.collector import Collector  # noqa: E402
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


def _misshaped_heartbeat(channel_count, sample_count):
    """A HEARTBEAT header with nonzero counts but still 26 bytes (valid CRC, wrong shape)."""
    header = struct.pack(
        HEADER_FMT, MAGIC, VERSION, MSG_HEARTBEAT, 1, 0, 0, 0, channel_count, sample_count
    )
    return header + struct.pack("<H", crc16_ccitt_false(header))


def test_decode_rejects_misshaped_heartbeat():
    # Weak finding: a HEARTBEAT with channel_count=1, sample_count=0 is still 26 bytes, so
    # the length check passes; the control-plane shape check must reject it (fail closed).
    frame = _misshaped_heartbeat(channel_count=1, sample_count=0)
    assert len(frame) == 26
    try:
        decode(frame)
    except FramingError:
        pass
    else:
        raise AssertionError("decode accepted a mis-shaped HEARTBEAT")
    # A real heartbeat (0/0) still decodes fine.
    assert decode(encode_heartbeat(1, 0, 0, 3200)).is_heartbeat


class _NoReceiver:
    def packets(self):
        return iter(())


def _sample_pkt(node_id, seq):
    return decode(encode_sample_block(
        node_id=node_id, seq=seq, t_node_us=0, sample_rate_hz=1000, channel_count=1, samples=[[1]]
    ))


def test_stale_duplicate_does_not_erase_real_loss():
    # Weak finding: a stale duplicate of an already-seen seq was misread as a reorder and
    # decremented `lost`, undercounting real loss. It must count as a duplicate instead.
    col = Collector(_NoReceiver(), sinks=[])
    col.process(_sample_pkt(1, 0))
    col.process(_sample_pkt(1, 3))  # 1 and 2 lost -> lost = 2
    ns = col.stats.nodes[1]
    assert ns.lost == 2
    col.process(_sample_pkt(1, 0))  # stale duplicate of already-seen seq 0
    assert ns.duplicated == 1
    assert ns.reordered == 0
    assert ns.lost == 2  # real loss preserved (the bug decremented it to 1)


def test_reorder_stat_only_counts_actual_overtakes():
    from wiredaq.daq_sim.transports.impairment_transport import (
        ImpairmentConfig,
        ImpairmentTransport,
    )
    from wiredaq.daq_sim.transports.in_process import InProcessTransport

    # Held then flushed alone: nothing overtook it, so it is not a reorder.
    held_only = ImpairmentTransport(InProcessTransport(), ImpairmentConfig(reorder=1.0), seed=0)
    held_only.send(b"x" * 30)
    held_only.flush()
    assert held_only.stats.reordered == 0

    # Held, then a later frame overtakes it: that is a real reorder.
    swapped = ImpairmentTransport(InProcessTransport(), ImpairmentConfig(reorder=1.0), seed=0)
    swapped.send(b"a" * 30)
    swapped.send(b"b" * 30)
    assert swapped.stats.reordered == 1


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_raw_logger_archives_heartbeat_byte_identical(Path(d))
    test_stream_receiver_frames_heartbeat()
    test_drift_ppm_actually_diverges()
    test_corruption_is_always_crc_not_framing()
    test_decode_rejects_misshaped_heartbeat()
    test_stale_duplicate_does_not_erase_real_loss()
    test_reorder_stat_only_counts_actual_overtakes()
    print("all regression guards pass")
