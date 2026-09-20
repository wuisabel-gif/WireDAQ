"""
H753 protocol emission, verified without hardware.

The firmware maps a 16-bit ADC count onto WireDAQ int16 samples and encodes
with the existing C codec. This test uses the production Python codec and the
unchanged StreamReceiver → Collector path to prove the host side of that
contract. The C helper is checked separately by `make -C firmware/boards/nucleo_h753zi test`.
"""

from __future__ import annotations

from wiredaq.cli.hil import (
    H753_ADC_MIDSCALE,
    H753_NODE_ID,
    H753_SAMPLE_RATE_HZ,
    adc_mv_from_raw,
    adc_raw_from_sample,
    capture,
)
from wiredaq.protocol.codec import decode, encode_sample_block


class FakePort:
    """Stand-in for pyserial: read(n) returns up to n available bytes."""

    def __init__(self, data: bytes) -> None:
        self._buf = bytearray(data)
        self.closed = False

    def read(self, size: int) -> bytes:
        out = bytes(self._buf[:size])
        del self._buf[:size]
        return out

    def close(self) -> None:
        self.closed = True


def _h753_frame(adc_raw: int, seq: int, t_node_us: int) -> bytes:
    sample = adc_raw - H753_ADC_MIDSCALE
    return encode_sample_block(
        node_id=H753_NODE_ID,
        seq=seq,
        t_node_us=t_node_us,
        sample_rate_hz=H753_SAMPLE_RATE_HZ,
        channel_count=1,
        samples=[[sample]],
    )


def test_adc_mapping_round_trip():
    assert adc_raw_from_sample(-32768) == 0
    assert adc_raw_from_sample(0) == 32768
    assert adc_raw_from_sample(32767) == 65535
    assert adc_mv_from_raw(32768) == 1650


def test_python_codec_accepts_h753_shape():
    frame = _h753_frame(adc_raw=32768, seq=0, t_node_us=1000)
    assert len(frame) == 28
    packet = decode(frame)
    assert packet.node_id == H753_NODE_ID
    assert packet.seq == 0
    assert packet.sample_rate_hz == H753_SAMPLE_RATE_HZ
    assert packet.channel_count == 1
    assert packet.sample_count == 1
    assert packet.samples == [[0]]
    assert adc_raw_from_sample(packet.samples[0][0]) == 32768


def test_host_path_decodes_h753_stream_without_hardware(tmp_path):
    frames = b"".join(
        _h753_frame(adc_raw=raw, seq=seq, t_node_us=seq * 100_000)
        for seq, raw in enumerate((0, 32768, 65535, 1000, 50000))
    )
    # Startup identity text is sent before binary frames; the stream receiver
    # must skip it as resync rather than requiring a board-specific decoder.
    stream = b"WireDAQ NUCLEO-H753ZI\r\n" + frames
    csv_path = tmp_path / "h753.csv"
    port = FakePort(stream)
    collector, receiver, metrics, csv_logger = capture(
        port,
        packets=5,
        csv_path=str(csv_path),
        timeout_s=0.2,
        sleep_s=0.0,
        quiet=True,
    )

    assert receiver.stats.received == 5
    assert receiver.stats.crc_errors == 0
    assert receiver.stats.framing_errors == 0
    assert receiver.stats.resync_bytes >= len(b"WireDAQ NUCLEO-H753ZI\r\n")
    assert collector.stats.total_packets == 5
    assert collector.stats.total_samples == 5
    ns = collector.stats.nodes[H753_NODE_ID]
    assert ns.packets == 5
    assert ns.lost == 0
    assert ns.duplicated == 0
    assert ns.last_seq == 4
    assert metrics.packets == 5
    assert csv_logger is not None
    assert csv_logger.rows_written == 5
    assert port.closed
