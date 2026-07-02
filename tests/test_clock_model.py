"""
ClockModel oracle tests (ADR 0002).

The synthetic node injects a known ``drift_ppm``; the ground-station fit must recover it.
That closed loop — inject a ppm, get it back — is the ADR's built-in test oracle. We also
assert the two properties the ADR leans on: jitter *widens the confidence interval without
biasing the estimate*, and packet loss doesn't bias it (the fit only sees pairs that arrived).

    python3 tests/test_clock_model.py
    pytest tests/test_clock_model.py
"""

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiredaq.ground_station.timing import ClockModel  # noqa: E402
from wiredaq.daq_sim.collector.collector import Collector  # noqa: E402
from wiredaq.daq_sim.core.clock import SimClock  # noqa: E402
from wiredaq.daq_sim.nodes.synthetic_node import SyntheticNode  # noqa: E402
from wiredaq.daq_sim.transports.in_process import InProcessTransport  # noqa: E402
from wiredaq.ground_station.receiver import FrameReceiver  # noqa: E402
from wiredaq.protocol.codec import decode  # noqa: E402

_REF_TICK_US = 2500  # ideal block duration at the defaults (8 samples / 3200 Hz)


def drive_model(ppm, blocks=4000, jitter=0, drop_every=0, seed=0):
    """Stream one drifting node's (t_node, t_ref) pairs into a ClockModel.

    ``t_ref`` advances at the *true* cadence (that's the reference clock); the node's clock
    runs fast/slow by ``ppm``. ``jitter`` adds zero-mean noise to arrival; ``drop_every``
    simulates loss by never feeding those packets to the fit.
    """
    node = SyntheticNode(node_id=1, drift_ppm=ppm, seed=seed)
    rng = random.Random(seed)
    cm = ClockModel(1)
    for k in range(blocks):
        frame = node.next_frame()
        if drop_every and k % drop_every == 0:
            continue  # lost in transit — never anchors the fit
        t_node = decode(frame).t_node_us
        t_ref = k * _REF_TICK_US + (rng.randint(-jitter, jitter) if jitter else 0)
        cm.update(t_node, t_ref)
    return cm


def test_recovers_injected_ppm_including_sign():
    for ppm in (60.0, 120.0, 250.0, -80.0):
        cm = drive_model(ppm)
        assert cm.ready
        assert abs(cm.drift_ppm - ppm) < 0.5, (ppm, cm.drift_ppm)
        # The fit inverts: a node stamp maps back onto the reference within a few µs.
        t_ref = 1_000_000
        t_node = round((1 + ppm / 1e6) * t_ref)
        assert abs(cm.to_ref(t_node) - t_ref) < 5, (ppm, cm.to_ref(t_node))


def test_jitter_widens_interval_without_biasing():
    clean = drive_model(120.0, jitter=0)
    noisy = drive_model(120.0, jitter=300)
    # Estimate stays close in both; the interval reports the difference in confidence.
    assert abs(clean.drift_ppm - 120.0) < 0.5
    assert abs(noisy.drift_ppm - 120.0) < 5.0
    assert noisy.drift_ppm_stderr > 20 * clean.drift_ppm_stderr
    assert noisy.residual_std_us > 50  # residuals now reflect the ±300 µs jitter


def test_loss_does_not_bias():
    full = drive_model(120.0)
    lossy = drive_model(120.0, drop_every=3)  # ~1/3 of packets never arrive
    assert lossy.n < full.n
    assert abs(lossy.drift_ppm - 120.0) < 1.0


def test_collector_fits_each_node_end_to_end():
    # Mirror the demo path: two nodes with distinct drift, fitted inside the Collector.
    ppms = [60.0, 120.0]
    nodes = [SyntheticNode(node_id=i + 1, drift_ppm=p, seed=i) for i, p in enumerate(ppms)]
    ref = SimClock()
    transport = InProcessTransport()
    collector = Collector(FrameReceiver(transport), sinks=[], clock=ref)
    for k in range(3000):
        ref.set_to(k * _REF_TICK_US)
        for node in nodes:
            transport.send(node.next_frame())
            collector.run()
    collector.close()
    for node_id, ppm in zip((1, 2), ppms):
        cm = collector.stats.nodes[node_id].clock
        assert cm is not None and cm.ready
        assert abs(cm.drift_ppm - ppm) < 0.5, (node_id, cm.drift_ppm)


def test_not_ready_before_two_points():
    cm = ClockModel(7)
    assert not cm.ready
    assert cm.skew == 1.0
    assert math.isinf(cm.drift_ppm_stderr)
    cm.update(1000, 1000)
    assert not cm.ready  # one point can't define a slope


if __name__ == "__main__":
    test_recovers_injected_ppm_including_sign()
    test_jitter_widens_interval_without_biasing()
    test_loss_does_not_bias()
    test_collector_fits_each_node_end_to_end()
    test_not_ready_before_two_points()
    print("clock model oracle: all checks pass")
