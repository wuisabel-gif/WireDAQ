"""
CsvLogger — a Sink that writes decoded samples to CSV.

One row per sample (not per packet), with the per-sample timestamp reconstructed from
the block's ``t_node_us`` and declared sample rate — the schema's "one timestamp per
block" rule unrolled into a flat, analysis-friendly table.

If given a ``clock_lookup`` (ADR 0002), it also writes a ``t_ref_us`` column: each
sample's node-local time mapped onto the ground station's reference timeline via that
node's :class:`ClockModel`. That is the column you sort on to align samples *across*
nodes whose clocks drift. It is left blank until a node's model has converged.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable, Optional, TextIO

from wiredaq.protocol.codec import Packet
from wiredaq.daq_sim.core.interfaces import Sink


class CsvLogger(Sink):
    """Append every sample of every packet to a CSV file."""

    def __init__(
        self,
        path: str,
        max_channels: int = 8,
        clock_lookup: Optional[Callable[[int], object]] = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: Optional[TextIO] = self.path.open("w", newline="")
        self._writer = csv.writer(self._fh)
        self.max_channels = max_channels
        self.clock_lookup = clock_lookup
        self.rows_written = 0

        header = ["node_id", "seq", "sample_index", "t_sample_us"]
        if clock_lookup is not None:
            header.append("t_ref_us")
        header += [f"ch{c}" for c in range(max_channels)]
        self._writer.writerow(header)

    def consume(self, packet: Packet) -> None:
        if self._fh is None:
            raise RuntimeError("CsvLogger is closed")
        model = self.clock_lookup(packet.node_id) if self.clock_lookup is not None else None
        for i, row in enumerate(packet.samples):
            t_sample_us = packet.sample_time_us(i)
            fields = [packet.node_id, packet.seq, i, t_sample_us]
            if self.clock_lookup is not None:
                # Blank until the node's clock model has enough points to be trustworthy.
                fields.append(model.to_ref(t_sample_us) if model is not None and model.ready else "")
            channels = list(row[: self.max_channels])
            channels += [""] * (self.max_channels - len(channels))
            fields += channels
            self._writer.writerow(fields)
            self.rows_written += 1

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
