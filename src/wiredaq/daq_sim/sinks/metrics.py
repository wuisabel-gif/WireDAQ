"""
MetricsSink — a Sink that aggregates throughput counters.

Lightweight tally of packets/samples (overall and per node). Delivery-quality figures
(loss, reordering, duplicates) live on the Collector, which owns the sequence tracking;
this sink owns volume. Together they make the run summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from wiredaq.protocol.codec import Packet
from wiredaq.daq_sim.core.interfaces import Sink


@dataclass
class MetricsSink(Sink):
    packets: int = 0
    samples: int = 0
    packets_by_node: Dict[int, int] = field(default_factory=dict)
    samples_by_node: Dict[int, int] = field(default_factory=dict)

    def consume(self, packet: Packet) -> None:
        self.packets += 1
        self.samples += packet.sample_count
        self.packets_by_node[packet.node_id] = (
            self.packets_by_node.get(packet.node_id, 0) + 1
        )
        self.samples_by_node[packet.node_id] = (
            self.samples_by_node.get(packet.node_id, 0) + packet.sample_count
        )
