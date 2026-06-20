"""
CsvLogger — a Sink that writes decoded samples to CSV.

One row per sample (not per packet), with the per-sample timestamp reconstructed from
the block's ``t_node_us`` and declared sample rate — the schema's "one timestamp per
block" rule unrolled into a flat, analysis-friendly table.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional, TextIO

from wiredaq.protocol.codec import Packet
from wiredaq.daq_sim.core.interfaces import Sink


class CsvLogger(Sink):
    """Append every sample of every packet to a CSV file."""

    def __init__(self, path: str, max_channels: int = 8) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: Optional[TextIO] = self.path.open("w", newline="")
        self._writer = csv.writer(self._fh)
        self.max_channels = max_channels
        self.rows_written = 0

        header = ["node_id", "seq", "sample_index", "t_sample_us"]
        header += [f"ch{c}" for c in range(max_channels)]
        self._writer.writerow(header)

    def consume(self, packet: Packet) -> None:
        if self._fh is None:
            raise RuntimeError("CsvLogger is closed")
        for i, row in enumerate(packet.samples):
            channels = list(row[: self.max_channels])
            channels += [""] * (self.max_channels - len(channels))
            self._writer.writerow(
                [packet.node_id, packet.seq, i, packet.sample_time_us(i), *channels]
            )
            self.rows_written += 1

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
