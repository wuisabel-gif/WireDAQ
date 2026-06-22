"""
Tests for the latency/jitter model in ImpairmentTransport.

These pin the timing behavior the README advertises ("jitter, clocks that slowly drift")
and that previously had no code behind it: a frame is invisible until its delay elapses on
the clock, jitter makes frames overtake each other, and nothing is ever swallowed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiredaq.daq_sim.core.clock import SimClock  # noqa: E402
from wiredaq.daq_sim.transports.impairment_transport import (  # noqa: E402
    ImpairmentConfig,
    ImpairmentTransport,
)
from wiredaq.daq_sim.transports.in_process import InProcessTransport  # noqa: E402
from wiredaq.protocol.codec import decode, encode_sample_block  # noqa: E402


def _frame(seq):
    return encode_sample_block(node_id=1, seq=seq, t_node_us=0, sample_rate_hz=1000,
                               channel_count=1, samples=[[seq]])


def test_frame_is_invisible_until_delay_elapses():
    clk = SimClock()
    t = ImpairmentTransport(InProcessTransport(),
                            ImpairmentConfig(delay_us=1000), clock=clk)
    t.send(_frame(0))
    assert t.recv() is None          # delay not yet elapsed → nothing visible
    clk.advance(999)
    assert t.recv() is None          # still 1us short
    clk.advance(1)                   # now exactly at release time
    got = t.recv()
    assert got is not None and decode(got).seq == 0
    assert t.stats.delayed == 1
    assert t.stats.max_delay_us == 1000


def test_pure_delay_preserves_order():
    clk = SimClock()
    t = ImpairmentTransport(InProcessTransport(),
                            ImpairmentConfig(delay_us=500), clock=clk)
    for s in range(5):
        t.send(_frame(s))
        clk.advance(10)              # frames sent 10us apart, all same delay
    clk.advance(10_000)              # let everything become due
    seqs = []
    while (f := t.recv()) is not None:
        seqs.append(decode(f).seq)
    assert seqs == [0, 1, 2, 3, 4]   # equal delay → FIFO preserved


def test_jitter_can_reorder_frames():
    clk = SimClock()
    # Big jitter relative to send spacing → some frames overtake others.
    t = ImpairmentTransport(InProcessTransport(),
                            ImpairmentConfig(delay_us=1000, jitter_us=900),
                            seed=3, clock=clk)
    for s in range(20):
        t.send(_frame(s))
        clk.advance(50)
    clk.advance(100_000)
    seqs = []
    while (f := t.recv()) is not None:
        seqs.append(decode(f).seq)
    assert sorted(seqs) == list(range(20))   # no frame lost or duplicated...
    assert seqs != list(range(20))           # ...but order was disturbed by jitter


def test_flush_releases_everything_regardless_of_clock():
    clk = SimClock()
    t = ImpairmentTransport(InProcessTransport(),
                            ImpairmentConfig(delay_us=1_000_000), clock=clk)
    for s in range(3):
        t.send(_frame(s))
    assert t.recv() is None          # nothing due yet (clock hasn't moved)
    t.flush()                        # end-of-stream: force-release without waiting
    seqs = []
    while (f := t.recv()) is not None:
        seqs.append(decode(f).seq)
    assert sorted(seqs) == [0, 1, 2]
    assert len(t._scheduled) == 0    # buffer fully drained


def test_timed_run_is_reproducible():
    def run():
        clk = SimClock()
        t = ImpairmentTransport(InProcessTransport(),
                                ImpairmentConfig(delay_us=1000, jitter_us=500,
                                                 loss=0.1, duplicate=0.1),
                                seed=42, clock=clk)
        out = []
        for s in range(50):
            t.send(_frame(s))
            clk.advance(50)
            while (f := t.recv()) is not None:
                out.append(decode(f).seq)
        t.flush()
        while (f := t.recv()) is not None:
            out.append(decode(f).seq)
        return out

    assert run() == run()            # same seed + same clock script → identical timeline


def test_untimed_transport_needs_no_clock_tick():
    # delay=jitter=0 → behaves exactly like the original pass-through (no clock advance).
    t = ImpairmentTransport(InProcessTransport(), ImpairmentConfig())
    t.send(_frame(7))
    got = t.recv()
    assert got is not None and decode(got).seq == 7
    assert t.stats.delayed == 0
