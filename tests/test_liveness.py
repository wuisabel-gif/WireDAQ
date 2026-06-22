"""
Tests for Collector node-liveness tracking (clock + stale_after_us) and the way
heartbeat beacons share the data stream's sequence space.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiredaq.daq_sim.collector.collector import Collector  # noqa: E402
from wiredaq.daq_sim.core.clock import SimClock  # noqa: E402
from wiredaq.protocol.codec import decode, encode_heartbeat, encode_sample_block  # noqa: E402


class _NullReceiver:
    """Collector requires a receiver, but these tests drive packets in by hand."""

    def packets(self):
        return iter(())


def _data(node_id, seq):
    return decode(encode_sample_block(node_id=node_id, seq=seq, t_node_us=0,
                                      sample_rate_hz=1000, channel_count=1, samples=[[seq]]))


def _beat(node_id, seq):
    return decode(encode_heartbeat(node_id=node_id, seq=seq, t_node_us=0))


def test_node_goes_stale_after_silence():
    clk = SimClock()
    col = Collector(_NullReceiver(), [], clock=clk, stale_after_us=1000)

    clk.set_to(100)
    col.process(_data(1, 0))         # node 1 last seen at t=100
    assert col.stale_nodes() == []   # just seen → fresh

    clk.set_to(1100)                 # 1000us later — exactly at threshold, not over
    assert col.stale_nodes() == []
    clk.set_to(1101)                 # now strictly over the threshold
    assert col.stale_nodes() == [1]


def test_heartbeat_refreshes_liveness():
    clk = SimClock()
    col = Collector(_NullReceiver(), [], clock=clk, stale_after_us=1000)

    clk.set_to(0)
    col.process(_data(1, 0))
    clk.set_to(900)
    col.process(_beat(1, 1))         # a beacon counts as "still alive"
    clk.set_to(1800)                 # 1800us since data, but only 900us since the beat
    assert col.stale_nodes() == []
    assert col.stats.nodes[1].heartbeats == 1


def test_heartbeats_share_seq_space_for_loss_detection():
    col = Collector(_NullReceiver(), [])
    col.process(_data(1, 0))
    col.process(_beat(1, 1))         # beacon consumes seq 1
    col.process(_data(1, 2))
    # seqs 0,1,2 all present and contiguous → no loss
    assert col.stats.nodes[1].lost == 0

    # now drop seq 4 (a beacon) and jump to 5 → one lost
    col.process(_data(1, 3))
    col.process(_data(1, 5))
    assert col.stats.nodes[1].lost == 1


def test_liveness_disabled_without_clock():
    col = Collector(_NullReceiver(), [], stale_after_us=1000)  # no clock
    col.process(_data(1, 0))
    assert col.stale_nodes() == []   # safely a no-op
