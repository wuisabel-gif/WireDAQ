#!/usr/bin/env python3
"""
WireDAQ — serial / byte-stream slice (Phase 4 link, in software).

Same pipeline shape as run_slice.py, but the link is a raw **byte stream** instead of a
datagram transport:

    synthetic node(s)
        → NoisySerialTransport over LoopbackSerialTransport   (line noise + bit flips)
        → StreamReceiver        (find frames via the magic sync word; validate + CRC)
        → collector             (per-node seq tracking)        ← unchanged from run_slice
        → metrics (+ optional CSV)

The Collector, sinks, codec, and synthetic node are byte-for-byte the same objects
run_slice.py uses. Only the transport and receiver changed — which is the whole point of
the ports-and-adapters design: moving from a perfect datagram link to a noisy serial
byte stream is a wiring change, not a rewrite.

    python3 run_serial.py
    python3 run_serial.py --nodes 2 --packets 200 --garbage 0.4 --corrupt 0.01 --seed 9
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ground_station.receiver import StreamReceiver  # noqa: E402
from tools.daq_sim.collector.collector import Collector  # noqa: E402
from tools.daq_sim.nodes.synthetic_node import SyntheticNode  # noqa: E402
from tools.daq_sim.sinks.csv_logger import CsvLogger  # noqa: E402
from tools.daq_sim.sinks.metrics import MetricsSink  # noqa: E402
from tools.daq_sim.transports.serial_transport import (  # noqa: E402
    LoopbackSerialTransport,
    NoisySerialTransport,
    SerialNoiseConfig,
)


def run(args: argparse.Namespace):
    nodes = [
        SyntheticNode(
            node_id=n + 1,
            sample_rate_hz=args.rate,
            channel_count=args.channels,
            samples_per_block=args.block,
            max_packets=args.packets,
            drift_ppm=args.drift_ppm * (n + 1),
            seed=args.seed + n,
        )
        for n in range(args.nodes)
    ]

    inner = LoopbackSerialTransport(max_read=args.chunk)
    transport = NoisySerialTransport(
        inner,
        SerialNoiseConfig(
            garbage_prob=args.garbage,
            garbage_max=args.garbage_max,
            corrupt_prob=args.corrupt,
        ),
        seed=args.seed,
    )
    receiver = StreamReceiver(transport)
    metrics = MetricsSink()
    sinks = [metrics]
    csv_logger = CsvLogger(args.csv, max_channels=args.channels) if args.csv else None
    if csv_logger:
        sinks.append(csv_logger)
    collector = Collector(receiver, sinks)

    # Interleave the nodes onto one shared serial line, draining as we go.
    generators = [node.frames() for node in nodes]
    active = list(generators)
    while active:
        still = []
        for gen in active:
            frame = next(gen, None)
            if frame is not None:
                transport.send(frame)
                still.append(gen)
        collector.run()  # drain whatever has fully arrived so far
        active = still
    collector.run()
    collector.close()

    return collector, transport, receiver, metrics, csv_logger


def print_summary(args, collector, transport, receiver, csv_logger):
    stats = collector.stats
    n = transport.stats
    rx = receiver.stats
    print("=" * 70)
    print("WireDAQ — serial / byte-stream slice")
    print("=" * 70)
    print(
        f"config   nodes={args.nodes}  packets/node={args.packets}  "
        f"rate={args.rate}Hz  ch={args.channels}  block={args.block}  "
        f"recv_chunk={args.chunk}B  seed={args.seed}"
    )
    print(
        f"line     garbage_prob={args.garbage}  garbage_max={args.garbage_max}  "
        f"corrupt_prob={args.corrupt}"
    )
    print("-" * 70)
    print("serial line (honest fake, byte level)")
    print(
        f"  frame_bytes_sent={n.bytes_sent}  garbage_injected={n.garbage_injected}  "
        f"bytes_corrupted={n.bytes_corrupted}"
    )
    print("stream receiver (sync-word framing; shared w/ ground station)")
    print(
        f"  decoded={rx.received}  crc_errors={rx.crc_errors}  "
        f"framing_errors={rx.framing_errors}  resync_bytes={rx.resync_bytes}"
    )
    print("-" * 70)
    print(f"collector  packets={stats.total_packets}  samples={stats.total_samples}")
    print(f"  {'node':>4} {'pkts':>6} {'samples':>8} {'lost':>5} {'dup':>4} {'loss%':>7}")
    for node_id in sorted(stats.nodes):
        ns = stats.nodes[node_id]
        print(
            f"  {ns.node_id:>4} {ns.packets:>6} {ns.samples:>8} {ns.lost:>5} "
            f"{ns.duplicated:>4} {ns.loss_pct:>6.1f}%"
        )
    if csv_logger is not None:
        print("-" * 70)
        print(f"csv      {csv_logger.rows_written} sample rows → {args.csv}")
    print("=" * 70)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the WireDAQ serial byte-stream slice.")
    p.add_argument("--nodes", type=int, default=2)
    p.add_argument("--packets", type=int, default=150)
    p.add_argument("--rate", type=int, default=3200)
    p.add_argument("--channels", type=int, default=3)
    p.add_argument("--block", type=int, default=8)
    p.add_argument("--chunk", type=int, default=17, help="UART read size (bytes/recv)")
    p.add_argument("--garbage", type=float, default=0.3, help="line-noise probability per frame")
    p.add_argument("--garbage-max", type=int, default=8, help="max noise burst length")
    p.add_argument("--corrupt", type=float, default=0.004, help="per-byte bit-flip probability")
    p.add_argument("--drift-ppm", type=float, default=50.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--csv", default="out/serial_samples.csv", help="CSV output ('' to disable)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.csv == "":
        args.csv = None
    collector, transport, receiver, metrics, csv_logger = run(args)
    print_summary(args, collector, transport, receiver, csv_logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
