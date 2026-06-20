"""
StreamReceiver framing tests — the byte-stream / serial path.

These prove the receiver reassembles frames out of a raw byte stream under the conditions
a real serial line imposes: frames split across reads, line noise between frames, and
corrupted bytes. The safety invariant throughout: a packet is yielded only if it is
bit-identical to what was sent — corruption is never silently accepted.

    python3 tests/test_stream_receiver.py
    pytest tests/test_stream_receiver.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiredaq.ground_station.receiver import StreamReceiver  # noqa: E402
from wiredaq.protocol.codec import decode  # noqa: E402
from wiredaq.daq_sim.collector.collector import Collector  # noqa: E402
from wiredaq.daq_sim.nodes.synthetic_node import SyntheticNode  # noqa: E402
from wiredaq.daq_sim.sinks.metrics import MetricsSink  # noqa: E402
from wiredaq.daq_sim.transports.serial_transport import (  # noqa: E402
    LoopbackSerialTransport,
    NoisySerialTransport,
    SerialNoiseConfig,
)


def make_frames(count, node_id=1, seed=0):
    node = SyntheticNode(node_id=node_id, max_packets=count, seed=seed)
    return list(node.frames())


def drive(receiver, transport, stream, slice_len):
    """Feed the byte stream in small slices, draining the receiver between each, so the
    receiver must survive frames that span multiple reads."""
    out = []
    for i in range(0, len(stream), slice_len):
        transport.send(stream[i:i + slice_len])
        out.extend(receiver.packets())
    out.extend(receiver.packets())
    return out


def test_clean_stream_reassembles_across_reads():
    frames = make_frames(20)
    stream = b"".join(frames)
    transport = LoopbackSerialTransport(max_read=7)
    rx = StreamReceiver(transport)

    got = drive(rx, transport, stream, slice_len=3)  # tiny slices: frames always split

    assert len(got) == 20
    assert [p.seq for p in got] == list(range(20))
    assert got == [decode(f) for f in frames]  # bit-identical
    assert rx.stats.crc_errors == 0
    assert rx.stats.framing_errors == 0
    assert rx.stats.resync_bytes == 0


def test_line_noise_between_frames_is_resynced():
    frames = make_frames(15)
    gap = bytes(5)  # 5 zero bytes of line noise before every frame (no sync word in it)
    stream = b"".join(gap + f for f in frames)
    transport = LoopbackSerialTransport(max_read=9)
    rx = StreamReceiver(transport)

    got = drive(rx, transport, stream, slice_len=4)

    assert len(got) == 15
    assert got == [decode(f) for f in frames]
    assert rx.stats.crc_errors == 0
    assert rx.stats.resync_bytes == 5 * 15  # every noise byte accounted for, exactly


def test_corrupted_frames_rejected_and_seen_as_loss():
    frames = make_frames(30)
    # Corrupt one payload byte (after the 24-byte header) in three specific frames.
    targets = {7, 15, 22}
    mutated = []
    for i, f in enumerate(frames):
        if i in targets:
            b = bytearray(f)
            b[24] ^= 0x01  # flip a payload bit → CRC must fail
            mutated.append(bytes(b))
        else:
            mutated.append(f)
    stream = b"".join(mutated)

    transport = LoopbackSerialTransport(max_read=16)
    rx = StreamReceiver(transport)
    metrics = MetricsSink()
    collector = Collector(rx, [metrics])

    # Drive through the collector in slices.
    for i in range(0, len(stream), 11):
        transport.send(stream[i:i + 11])
        collector.run()
    collector.run()

    assert rx.stats.received == 27
    assert rx.stats.crc_errors == 3
    # The three rejected frames leave seq gaps the collector reports as loss.
    assert collector.stats.nodes[1].lost == 3
    assert metrics.packets == 27


def test_noisy_serial_never_yields_corrupted_data():
    # Heavy random noise: the safety property must still hold — no false accepts.
    frames = make_frames(60, seed=2)
    originals = {decode(f).seq: decode(f) for f in frames}

    inner = LoopbackSerialTransport(max_read=13)
    transport = NoisySerialTransport(
        inner, SerialNoiseConfig(garbage_prob=0.5, garbage_max=6, corrupt_prob=0.02),
        seed=5,
    )
    rx = StreamReceiver(transport)

    got = []
    for f in frames:
        transport.send(f)
        got.extend(rx.packets())
    got.extend(rx.packets())

    # Every packet that came through is bit-identical to the one that was sent.
    for p in got:
        assert p == originals[p.seq], f"corrupted packet accepted at seq {p.seq}"
    assert transport.stats.garbage_injected > 0
    assert transport.stats.bytes_corrupted > 0
    assert len(got) <= 60


def test_multinode_stream_demuxed_with_loss():
    # Two nodes interleaved on one line; drop one whole frame of node 2's bytes.
    a = make_frames(10, node_id=1, seed=1)
    b = make_frames(10, node_id=2, seed=2)
    interleaved = []
    for fa, fb in zip(a, b):
        interleaved.append(fa)
        interleaved.append(fb)
    del interleaved[5]  # drop one frame entirely (a node-2 frame, seq 2)
    stream = b"".join(interleaved)

    transport = LoopbackSerialTransport(max_read=20)
    rx = StreamReceiver(transport)
    collector = Collector(rx, [])
    transport.send(stream)
    collector.run()

    assert collector.stats.nodes[1].lost == 0   # node 1 intact
    assert collector.stats.nodes[2].lost == 1   # node 2 missing one
    assert rx.stats.received == 19


def _run_standalone():
    tests = [
        test_clean_stream_reassembles_across_reads,
        test_line_noise_between_frames_is_resynced,
        test_corrupted_frames_rejected_and_seen_as_loss,
        test_noisy_serial_never_yields_corrupted_data,
        test_multinode_stream_demuxed_with_loss,
    ]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"All {len(tests)} stream-receiver checks passed.")


if __name__ == "__main__":
    _run_standalone()
