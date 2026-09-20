#!/usr/bin/env python3
"""
Capture WireDAQ frames from a real serial device.

This is the hardware-in-the-loop wiring change, not a new decoder:

    board UART
        → SerialPortTransport
        → StreamReceiver
        → Collector
        → metrics / optional CSV

    wiredaq-hil --port /dev/ttyACM0 --packets 30
    python -m wiredaq.cli.hil --port COM5 --csv out/h753.csv
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from wiredaq.daq_sim.collector.collector import Collector
from wiredaq.daq_sim.core.clock import WallClock
from wiredaq.daq_sim.core.interfaces import Sink
from wiredaq.daq_sim.sinks.csv_logger import CsvLogger
from wiredaq.daq_sim.sinks.metrics import MetricsSink
from wiredaq.daq_sim.transports.serial_port import SerialPortTransport, open_serial_port
from wiredaq.ground_station.receiver import StreamReceiver
from wiredaq.protocol.codec import Packet

# Must match firmware/boards/nucleo_h753zi/Core/h753_protocol.h
H753_NODE_ID = 1
H753_SAMPLE_RATE_HZ = 10
H753_ADC_MIDSCALE = 32768
H753_ADC_REFERENCE_MV = 3300
H753_ADC_MAX_COUNT = 65535


def adc_raw_from_sample(sample: int) -> int:
    """Invert the firmware mapping: wire = raw - 32768."""
    return sample + H753_ADC_MIDSCALE


def adc_mv_from_raw(raw: int) -> int:
    return (raw * H753_ADC_REFERENCE_MV) // H753_ADC_MAX_COUNT


class PrintSink(Sink):
    """Print each decoded sample with reconstructed ADC counts."""

    def consume(self, packet: Packet) -> None:
        if packet.is_heartbeat or not packet.samples:
            print(
                f"heartbeat node={packet.node_id} seq={packet.seq} "
                f"t_node_us={packet.t_node_us}"
            )
            return
        sample = packet.samples[0][0]
        raw = adc_raw_from_sample(sample)
        print(
            f"node={packet.node_id} seq={packet.seq} t_node_us={packet.t_node_us} "
            f"sample={sample} adc_raw={raw} adc_mv={adc_mv_from_raw(raw)}"
        )


def capture(
    port,
    packets: int = 30,
    csv_path: Optional[str] = None,
    max_read: int = 256,
    timeout_s: float = 15.0,
    sleep_s: float = 0.01,
    quiet: bool = False,
):
    """Drain frames from any object exposing read(n) -> bytes."""
    transport = SerialPortTransport(port, max_read=max_read)
    receiver = StreamReceiver(transport)
    metrics = MetricsSink()
    sinks: list[Sink] = [metrics]
    if not quiet:
        sinks.append(PrintSink())
    csv_logger = CsvLogger(csv_path, max_channels=1) if csv_path else None
    if csv_logger is not None:
        sinks.append(csv_logger)
    collector = Collector(receiver, sinks, clock=WallClock())

    deadline = time.monotonic() + timeout_s
    while collector.stats.total_packets < packets:
        collector.run()
        if time.monotonic() >= deadline:
            break
        time.sleep(sleep_s)

    collector.close()
    transport.close()
    return collector, receiver, metrics, csv_logger


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Decode WireDAQ frames from a serial port with the existing host path."
    )
    p.add_argument("--port", required=True, help="serial device, e.g. /dev/ttyACM0 or COM5")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--packets", type=int, default=30, help="stop after this many decoded frames")
    p.add_argument("--timeout", type=float, default=15.0, help="seconds to wait for --packets")
    p.add_argument("--csv", default="", help="optional CSV path (empty to disable)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    port = open_serial_port(args.port, baudrate=args.baud)
    csv_path = args.csv if args.csv else None
    collector, receiver, metrics, csv_logger = capture(
        port,
        packets=args.packets,
        csv_path=csv_path,
        timeout_s=args.timeout,
    )
    stats = collector.stats
    rx = receiver.stats
    print("-" * 70)
    print(
        f"decoded={rx.received} crc_errors={rx.crc_errors} "
        f"framing_errors={rx.framing_errors} resync_bytes={rx.resync_bytes}"
    )
    print(f"collector packets={stats.total_packets} samples={stats.total_samples}")
    for node_id in sorted(stats.nodes):
        ns = stats.nodes[node_id]
        print(
            f"  node={ns.node_id} pkts={ns.packets} samples={ns.samples} "
            f"lost={ns.lost} dup={ns.duplicated}"
        )
    print(f"metrics packets={metrics.packets} samples={metrics.samples}")
    if csv_logger is not None:
        print(f"csv {csv_logger.rows_written} sample rows -> {args.csv}")
    if stats.total_packets == 0:
        print("no frames decoded; check port, baud, and that the board is streaming", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
