"""
Collector — the orchestrator (the hexagon's core).

Pulls decoded packets from a :class:`Receiver` and fans them out to one or more
:class:`Sink` s, tracking each node's sequence numbers to detect **loss** (a forward
gap), **reordering / late arrival** (a sequence that goes backwards), and **duplicates**
(a sequence seen again). It depends only on the ports — never on a concrete transport,
node, or sink — so it is written once and survives every phase transition unchanged.

Sequence arithmetic is modulo 2^32 (the ``seq`` field wraps), so comparisons use a
signed delta on the 32-bit ring rather than plain ``<`` / ``>``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from wiredaq.protocol.codec import Packet
from wiredaq.daq_sim.core.clock import Clock
from wiredaq.daq_sim.core.interfaces import Receiver, Sink

_SEQ_MOD = 1 << 32
_SEQ_HALF = 1 << 31


def seq_delta(a: int, b: int) -> int:
    """Signed distance ``a - b`` on the 32-bit sequence ring (result in [-2^31, 2^31))."""
    return ((a - b + _SEQ_HALF) % _SEQ_MOD) - _SEQ_HALF


@dataclass
class NodeStats:
    """Per-node delivery quality, derived purely from the seq field."""

    node_id: int
    packets: int = 0          # valid packets accepted from this node
    samples: int = 0          # total samples across those packets
    lost: int = 0             # estimated packets missing (sum of forward gaps)
    reordered: int = 0        # packets that arrived older than the highest seen
    duplicated: int = 0       # packets whose seq was already seen
    heartbeats: int = 0       # liveness beacons seen (a subset of `packets`)
    first_seq: int = -1
    last_seq: int = -1        # highest in-order seq observed
    last_seen_us: int = -1    # clock time the last frame from this node arrived (-1 = never)

    @property
    def expected(self) -> int:
        """Packets that *should* have arrived in-order = accepted + lost."""
        return self.packets + self.lost

    @property
    def loss_pct(self) -> float:
        exp = self.expected
        return 100.0 * self.lost / exp if exp else 0.0


@dataclass
class CollectorStats:
    nodes: Dict[int, NodeStats] = field(default_factory=dict)
    total_packets: int = 0
    total_samples: int = 0

    def _node(self, node_id: int) -> NodeStats:
        ns = self.nodes.get(node_id)
        if ns is None:
            ns = NodeStats(node_id=node_id)
            self.nodes[node_id] = ns
        return ns


class Collector:
    """Reads from a Receiver, tracks delivery quality, fans out to Sinks.

    If given a :class:`Clock` and a ``stale_after_us`` threshold, it also tracks node
    *liveness*: each frame (data or HEARTBEAT beacon) refreshes the node's last-seen time,
    and :meth:`stale_nodes` reports any node that has gone silent for longer than the
    threshold — the "is that sensor still alive?" question avionics has to answer in flight.
    """

    def __init__(
        self,
        receiver: Receiver,
        sinks: Iterable[Sink],
        clock: Optional[Clock] = None,
        stale_after_us: Optional[int] = None,
    ) -> None:
        self.receiver = receiver
        self.sinks: List[Sink] = list(sinks)
        self.stats = CollectorStats()
        self.clock = clock
        self.stale_after_us = stale_after_us

    def _track(self, packet: Packet) -> None:
        ns = self.stats._node(packet.node_id)
        ns.packets += 1
        ns.samples += packet.sample_count
        if packet.is_heartbeat:
            ns.heartbeats += 1
        if self.clock is not None:
            ns.last_seen_us = self.clock.now_us()

        if ns.last_seq < 0:
            ns.first_seq = packet.seq
            ns.last_seq = packet.seq
            return

        delta = seq_delta(packet.seq, ns.last_seq)
        if delta == 1:
            ns.last_seq = packet.seq            # perfectly in order
        elif delta > 1:
            ns.lost += delta - 1                # forward gap → that many lost
            ns.last_seq = packet.seq
        elif delta == 0:
            ns.duplicated += 1                  # same seq again
        else:  # delta < 0
            ns.reordered += 1                   # arrived older than the high-water mark
            # A reordered packet often fills a gap we already counted as lost.
            if ns.lost > 0:
                ns.lost -= 1

    def process(self, packet: Packet) -> None:
        """Track one packet and deliver it to every sink."""
        self._track(packet)
        self.stats.total_packets += 1
        self.stats.total_samples += packet.sample_count
        for sink in self.sinks:
            sink.consume(packet)

    def run(self) -> CollectorStats:
        """Drain everything currently available from the receiver. Idempotent to call
        repeatedly as more frames arrive at the transport."""
        for packet in self.receiver.packets():
            self.process(packet)
        return self.stats

    def stale_nodes(self, now_us: Optional[int] = None) -> List[int]:
        """Node ids that have gone silent longer than ``stale_after_us``.

        Requires a clock and threshold (set on construction); returns ``[]`` otherwise.
        ``now_us`` defaults to the clock's current time. A node that has never been seen
        is not reported (you cannot lose what never arrived)."""
        if self.clock is None or self.stale_after_us is None:
            return []
        now = self.clock.now_us() if now_us is None else now_us
        return [
            ns.node_id
            for ns in self.stats.nodes.values()
            if ns.last_seen_us >= 0 and (now - ns.last_seen_us) > self.stale_after_us
        ]

    def close(self) -> None:
        for sink in self.sinks:
            sink.close()
