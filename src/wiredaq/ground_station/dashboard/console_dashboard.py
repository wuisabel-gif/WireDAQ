"""
ConsoleDashboardSink — the live ground-station dashboard, in the terminal.

The real-time counterpart to the design-time what-if console
(``tools/dashboard/index.html``). Where that one *models* a hypothetical
configuration, this one *displays* the packets actually flowing through the collector, in
real time: per-node packet counts and the most recent Z-axis reading, refreshed every
``every`` packets. It is a plain :class:`Sink`, so it can run alongside the logger and
metrics on the same collector.

This is intentionally a minimal text dashboard (no curses, no deps) — enough to watch a
live or replayed session. A richer web dashboard would live here too, fed the same way.
"""

from __future__ import annotations

import sys
from typing import Dict, Optional, TextIO

from wiredaq.protocol.codec import Packet
from wiredaq.daq_sim.core.interfaces import Sink


class ConsoleDashboardSink(Sink):
    """Print a compact per-node status line every ``every`` packets."""

    def __init__(self, every: int = 50, stream: Optional[TextIO] = None) -> None:
        if every < 1:
            raise ValueError("every must be >= 1")
        self.every = every
        self._stream: TextIO = stream if stream is not None else sys.stdout
        self._count = 0
        self._packets_by_node: Dict[int, int] = {}
        self._last_value: Dict[int, int] = {}  # last sample's last channel, per node

    def consume(self, packet: Packet) -> None:
        self._count += 1
        self._packets_by_node[packet.node_id] = (
            self._packets_by_node.get(packet.node_id, 0) + 1
        )
        if packet.samples:
            self._last_value[packet.node_id] = packet.samples[-1][-1]
        if self._count % self.every == 0:
            self._render()

    def _render(self) -> None:
        parts = []
        for node_id in sorted(self._packets_by_node):
            n = self._packets_by_node[node_id]
            last = self._last_value.get(node_id, 0)
            parts.append(f"node{node_id}: {n:>5} pkts (last={last:>6})")
        line = f"[live {self._count:>6} pkts]  " + "   ".join(parts)
        self._stream.write("\r" + line)
        self._stream.flush()

    def close(self) -> None:
        # Leave the final status line in place with a trailing newline.
        if self._count:
            self._render()
        self._stream.write("\n")
        self._stream.flush()
