#!/usr/bin/env python3
"""
WireDAQ — first vertical slice (ADR 0001, "proof of seam").

Wires the deliberately-tiny end-to-end pipeline the ADR specifies:

    synthetic accel node(s)
        → impairment transport   (the honest fake: loss / dup / reorder / corruption)
        → frame receiver         (validate + CRC + decode; shared with the ground station)
        → collector              (per-node seq tracking: loss / reorder / duplicate)
        → CSV logger + metrics

Every stage sits behind a port, so a real sensor board could replace a synthetic node
with nothing downstream changing — which is the whole point of the architecture.

Pure standard library; no build step. After `pip install -e .`:

    wiredaq-slice
    wiredaq-slice --nodes 3 --packets 200 --loss 0.05 --reorder 0.03 --seed 7

or without installing: `python -m wiredaq.cli.slice ...`.
"""

from __future__ import annotations

import argparse

from wiredaq.ground_station.dashboard import ConsoleDashboardSink
from wiredaq.ground_station.logger import RawFrameLogger
from wiredaq.ground_station.receiver import FrameReceiver
from wiredaq.daq_sim.collector.collector import Collector
from wiredaq.daq_sim.nodes.synthetic_node import SyntheticNode
from wiredaq.daq_sim.sinks.csv_logger import CsvLogger
from wiredaq.daq_sim.sinks.metrics import MetricsSink
from wiredaq.daq_sim.transports.impairment_transport import (
    ImpairmentConfig,
    ImpairmentTransport,
)
from wiredaq.daq_sim.transports.in_process import InProcessTransport
from wiredaq.daq_sim.transports.udp_transport import UdpTransport


def build_nodes(args: argparse.Namespace) -> list:
    nodes = []
    for n in range(args.nodes):
        nodes.append(
            SyntheticNode(
                node_id=n + 1,
                sample_rate_hz=args.rate,
                channel_count=args.channels,
                samples_per_block=args.block,
                max_packets=args.packets,
                # give each node a distinct clock drift so skew is visible
                drift_ppm=args.drift_ppm * (n + 1),
                seed=args.seed + n,
            )
        )
    return nodes


def _final_drain(collector: Collector, inner, transport_kind: str) -> None:
    """Catch any in-flight packets after the last send. For a real UDP link, datagrams
    may still be arriving, so poll the socket briefly until it goes quiet."""
    if transport_kind == "udp":
        import select
        import time

        idle_rounds = 0
        end = time.monotonic() + 1.5
        while idle_rounds < 5 and time.monotonic() < end:
            select.select([inner._rx], [], [], 0.05)
            before = collector.stats.total_packets
            collector.run()
            idle_rounds = idle_rounds + 1 if collector.stats.total_packets == before else 0
    else:
        collector.run()


def run(args: argparse.Namespace) -> Collector:
    nodes = build_nodes(args)

    link = UdpTransport() if args.transport == "udp" else InProcessTransport()
    transport = ImpairmentTransport(
        link,
        ImpairmentConfig(
            loss=args.loss,
            duplicate=args.duplicate,
            reorder=args.reorder,
            corrupt=args.corrupt,
        ),
        seed=args.seed,
    )

    receiver = FrameReceiver(transport)
    metrics = MetricsSink()
    sinks = [metrics]

    csv_logger = None
    if args.csv:
        csv_logger = CsvLogger(args.csv, max_channels=args.channels)
        sinks.append(csv_logger)

    raw_logger = None
    if args.raw_log:
        raw_logger = RawFrameLogger(args.raw_log)
        sinks.append(raw_logger)

    dashboard = None
    if args.dashboard:
        dashboard = ConsoleDashboardSink(every=args.dashboard_every)
        sinks.append(dashboard)

    collector = Collector(receiver, sinks)

    # Round-robin the nodes onto the shared link (their seqs interleave), draining as we
    # go so a real socket buffer never overflows.
    generators = [node.frames() for node in nodes]
    active = list(generators)
    while active:
        still_active = []
        for gen in active:
            frame = next(gen, None)
            if frame is not None:
                transport.send(frame)
                still_active.append(gen)
        collector.run()
        active = still_active
    transport.flush()  # release any frame held back for reordering (keeps link open)
    _final_drain(collector, link, args.transport)
    transport.close()
    collector.close()

    collector._metrics = metrics  # stash for the summary printer
    collector._transport = transport
    collector._receiver = receiver
    collector._csv = csv_logger
    collector._raw = raw_logger
    return collector


def print_summary(args: argparse.Namespace, collector: Collector) -> None:
    stats = collector.stats
    imp = collector._transport.stats
    rcv = collector._receiver.stats

    print("=" * 66)
    print("WireDAQ — first vertical slice")
    print("=" * 66)
    print(
        f"config   transport={args.transport}  nodes={args.nodes}  "
        f"packets/node={args.packets}  rate={args.rate}Hz  ch={args.channels}  "
        f"block={args.block}  seed={args.seed}"
    )
    print(
        f"link     loss={args.loss}  dup={args.duplicate}  "
        f"reorder={args.reorder}  corrupt={args.corrupt}"
    )
    print("-" * 66)
    print("transport (honest fake)")
    print(
        f"  offered={imp.offered}  delivered={imp.delivered}  dropped={imp.dropped}  "
        f"duplicated={imp.duplicated}  reordered={imp.reordered}  corrupted={imp.corrupted}"
    )
    print("receiver (shared w/ ground station)")
    print(
        f"  decoded={rcv.received}  crc_errors={rcv.crc_errors}  "
        f"framing_errors={rcv.framing_errors}"
    )
    print("-" * 66)
    print(f"collector  packets={stats.total_packets}  samples={stats.total_samples}")
    header = f"  {'node':>4} {'pkts':>6} {'samples':>8} {'lost':>5} {'reord':>6} {'dup':>4} {'loss%':>7}"
    print(header)
    for node_id in sorted(stats.nodes):
        ns = stats.nodes[node_id]
        print(
            f"  {ns.node_id:>4} {ns.packets:>6} {ns.samples:>8} {ns.lost:>5} "
            f"{ns.reordered:>6} {ns.duplicated:>4} {ns.loss_pct:>6.1f}%"
        )
    if collector._csv is not None or collector._raw is not None:
        print("-" * 66)
    if collector._csv is not None:
        print(f"csv      {collector._csv.rows_written} sample rows → {args.csv}")
    if collector._raw is not None:
        print(
            f"raw log  {collector._raw.frames_written} frames, "
            f"{collector._raw.bytes_written} bytes → {args.raw_log}"
        )
    print("=" * 66)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the WireDAQ first vertical slice.")
    p.add_argument("--nodes", type=int, default=2, help="number of synthetic nodes")
    p.add_argument("--packets", type=int, default=100, help="packets emitted per node")
    p.add_argument("--rate", type=int, default=3200, help="sample rate (Hz)")
    p.add_argument("--channels", type=int, default=3, help="channels per sample")
    p.add_argument("--block", type=int, default=8, help="samples per packet")
    p.add_argument("--loss", type=float, default=0.02, help="per-frame loss probability")
    p.add_argument("--duplicate", type=float, default=0.01, help="duplication probability")
    p.add_argument("--reorder", type=float, default=0.02, help="reorder probability")
    p.add_argument("--corrupt", type=float, default=0.01, help="corruption probability")
    p.add_argument("--drift-ppm", type=float, default=50.0, help="clock drift per node (ppm)")
    p.add_argument("--seed", type=int, default=1, help="RNG seed (reproducible runs)")
    p.add_argument(
        "--transport",
        choices=("local", "udp"),
        default="local",
        help="'local' in-process queue, or 'udp' over real loopback sockets",
    )
    p.add_argument(
        "--csv",
        default="out/slice_samples.csv",
        help="CSV output path ('' to disable)",
    )
    p.add_argument(
        "--raw-log",
        default="",
        help="raw-frame archive path for replay ('' to disable)",
    )
    p.add_argument("--dashboard", action="store_true", help="show the live console dashboard")
    p.add_argument("--dashboard-every", type=int, default=50, help="dashboard refresh interval (packets)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.csv == "":
        args.csv = None
    collector = run(args)
    print_summary(args, collector)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
