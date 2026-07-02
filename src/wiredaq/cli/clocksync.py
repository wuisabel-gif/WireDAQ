#!/usr/bin/env python3
"""
WireDAQ — clock-domain reconstruction demo (ADR 0002).

Two (or more) synthetic nodes run on independent, drifting clocks. Each stamps packets
with its own uncorrected ``t_node_us``; the ground station never changes those. Instead the
:class:`Collector` fits a per-node :class:`ClockModel` against its own reference clock
(sampled at packet arrival) and recovers each node's drift and offset — which lets samples
from differently-drifting nodes be placed on one timeline.

Because the reference clock here advances at the true cadence while each node's clock runs
fast/slow by its injected ``drift_ppm``, the recovered ppm should match the injected ppm:
the simulator is its own oracle. Optional ``--jitter-us`` perturbs arrival times to show the
estimate's confidence interval widen while the estimate stays unbiased.

    wiredaq-clocksync
    wiredaq-clocksync --nodes 3 --blocks 6000 --drift-ppm 40 --jitter-us 300 --seed 7

or without installing: `python -m wiredaq.cli.clocksync ...`.
"""

from __future__ import annotations

import argparse
import random

from wiredaq.protocol.codec import decode
from wiredaq.daq_sim.collector.collector import Collector
from wiredaq.daq_sim.core.clock import SimClock
from wiredaq.daq_sim.nodes.synthetic_node import SyntheticNode
from wiredaq.daq_sim.transports.in_process import InProcessTransport
from wiredaq.ground_station.receiver import FrameReceiver


def run(args: argparse.Namespace) -> Collector:
    ref_tick_us = max(1, round(args.block * 1_000_000 / args.rate))
    rng = random.Random(args.seed)

    nodes = [
        SyntheticNode(
            node_id=i + 1,
            sample_rate_hz=args.rate,
            channel_count=args.channels,
            samples_per_block=args.block,
            drift_ppm=args.drift_ppm * (i + 1),  # each node a distinct, known drift
            seed=args.seed + i,
        )
        for i in range(args.nodes)
    ]

    ref_clock = SimClock()
    transport = InProcessTransport()
    collector = Collector(FrameReceiver(transport), sinks=[], clock=ref_clock)
    # Remember each node's most recent t_node_us, to show the timeline correlation at the end.
    last_t_node: dict[int, int] = {}

    for k in range(args.blocks):
        base_us = k * ref_tick_us
        # One arrival per node this block, each with its own zero-mean jitter; deliver in
        # arrival order so the reference clock only moves forward.
        arrivals = []
        for node in nodes:
            frame = node.next_frame()
            jitter = rng.randint(-args.jitter_us, args.jitter_us) if args.jitter_us else 0
            arrivals.append((base_us + jitter, node.node_id, frame))
        for arrival_us, node_id, frame in sorted(arrivals):
            ref_clock.set_to(max(ref_clock.now_us(), arrival_us))
            transport.send(frame)
            collector.run()  # decode + track + fit, at this reference instant
            last_t_node[node_id] = decode(frame).t_node_us

    collector.close()
    collector._last_t_node = last_t_node  # stash for the printer
    collector._ref_now = ref_clock.now_us()
    return collector


def print_summary(args: argparse.Namespace, collector: Collector) -> None:
    stats = collector.stats
    print("=" * 74)
    print("WireDAQ — clock-domain reconstruction (ADR 0002)")
    print("=" * 74)
    ref_tick_us = max(1, round(args.block * 1_000_000 / args.rate))
    print(
        f"config   nodes={args.nodes}  blocks={args.blocks}  rate={args.rate}Hz  "
        f"block={args.block}  ref_tick={ref_tick_us}us  jitter=±{args.jitter_us}us  seed={args.seed}"
    )
    print("-" * 74)
    print("per-node clock fit   t_node ≈ skew·t_ref + offset   ((skew−1)·1e6 = drift ppm)")
    print(
        f"  {'node':>4} {'injected_ppm':>13} {'recovered_ppm':>14} {'±stderr':>9} "
        f"{'resid_us':>9} {'pkts':>6}"
    )
    for node_id in sorted(stats.nodes):
        ns = stats.nodes[node_id]
        injected = args.drift_ppm * node_id
        cm = ns.clock
        if cm is None or not cm.ready:
            print(f"  {node_id:>4} {injected:>13.3f} {'(not ready)':>14}")
            continue
        print(
            f"  {node_id:>4} {injected:>13.3f} {cm.drift_ppm:>14.3f} "
            f"{cm.drift_ppm_stderr:>9.3f} {cm.residual_std_us:>9.2f} {ns.packets:>6}"
        )

    # Correlate the nodes onto one timeline: each node's latest sample, raw vs reconstructed.
    ref_now = collector._ref_now
    last_t_node = collector._last_t_node
    print("-" * 74)
    print(f"timeline correlation   reference 'now' ≈ {ref_now} us")
    print(f"  {'node':>4} {'raw t_node_us':>15} {'→ t_ref_us (est)':>18} {'err_us':>8}")
    raw_vals, ref_errs = [], []
    for node_id in sorted(stats.nodes):
        cm = stats.nodes[node_id].clock
        if cm is None or not cm.ready or node_id not in last_t_node:
            continue
        raw = last_t_node[node_id]
        est_ref = cm.to_ref(raw)
        raw_vals.append(raw)
        ref_errs.append(abs(est_ref - ref_now))
        print(f"  {node_id:>4} {raw:>15} {est_ref:>18} {abs(est_ref - ref_now):>8}")
    if len(raw_vals) >= 2:
        spread_raw = max(raw_vals) - min(raw_vals)
        print(
            f"  raw node clocks differ by {spread_raw} us; reconstructed onto one timeline "
            f"within {max(ref_errs)} us of the reference."
        )
    print("=" * 74)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Recover per-node clock drift and align nodes onto one timeline (ADR 0002).")
    p.add_argument("--nodes", type=int, default=2, help="number of drifting synthetic nodes")
    p.add_argument("--blocks", type=int, default=4000, help="sample blocks emitted per node")
    p.add_argument("--rate", type=int, default=3200, help="sample rate (Hz)")
    p.add_argument("--channels", type=int, default=3, help="channels per sample")
    p.add_argument("--block", type=int, default=8, help="samples per block")
    p.add_argument("--drift-ppm", type=float, default=60.0,
                   help="base clock drift; node i drifts by this × i (ppm)")
    p.add_argument("--jitter-us", type=int, default=0,
                   help="±uniform jitter on packet arrival (widens the estimate, no bias)")
    p.add_argument("--seed", type=int, default=1, help="RNG seed (reproducible runs)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    collector = run(args)
    print_summary(args, collector)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
