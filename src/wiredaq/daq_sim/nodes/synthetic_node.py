"""
SyntheticNode — a synthetic 3-axis accelerometer (ADR 0001 build step 5).

Generates a plausible accelerometer signal (a sine on X/Y, gravity plus a small wobble
on Z, seeded noise on all axes), packs it into SAMPLE_BLOCK frames with the production
codec, and hands back complete on-wire bytes. It is a drop-in behind the
:class:`SensorNode` port: a real board replaces it later with nothing downstream
changing.

Two honest-fake details matter here:

* **Clock drift.** Each node advances its own ``t_node_us`` by the block duration scaled
  by ``(1 + drift_ppm/1e6)``, so two nodes started together slowly diverge — the clock
  skew that ADR 0002 must eventually resolve, made visible from Phase 1.
* **Per-node sequence.** ``seq`` increments by exactly one per frame and wraps at 2^32,
  so the Collector can detect loss and reordering from it alone.
"""

from __future__ import annotations

import math
import random
from typing import Optional

from wiredaq.protocol.codec import encode_heartbeat, encode_sample_block
from wiredaq.daq_sim.core.interfaces import SensorNode

_INT16_MIN, _INT16_MAX = -32768, 32767


def _clip16(value: float) -> int:
    return max(_INT16_MIN, min(_INT16_MAX, int(round(value))))


class SyntheticNode(SensorNode):
    """A synthetic accelerometer that emits SAMPLE_BLOCK frames."""

    def __init__(
        self,
        node_id: int,
        sample_rate_hz: int = 3200,
        channel_count: int = 3,
        samples_per_block: int = 8,
        max_packets: Optional[int] = None,
        start_seq: int = 0,
        t_start_us: int = 0,
        drift_ppm: float = 0.0,
        noise_counts: int = 8,
        seed: int = 0,
        heartbeat_every: int = 0,
    ) -> None:
        if channel_count < 1:
            raise ValueError("channel_count must be >= 1")
        if heartbeat_every < 0:
            raise ValueError("heartbeat_every must be >= 0 (0 disables beacons)")
        self.node_id = node_id
        self.sample_rate_hz = sample_rate_hz
        self.channel_count = channel_count
        self.samples_per_block = samples_per_block
        self.max_packets = max_packets
        self.drift_ppm = drift_ppm
        self.noise_counts = noise_counts
        self.heartbeat_every = heartbeat_every

        self._seq = start_seq & 0xFFFFFFFF
        self._t_node_us = t_start_us & 0xFFFFFFFFFFFFFFFF
        self._emitted = 0
        self._blocks_since_hb = 0  # data blocks since the last heartbeat beacon
        self._sample_index = 0  # global sample counter, for signal phase continuity
        self._rng = random.Random(seed)

        # Block duration on this node's *own* (drifting) clock, in microseconds.
        ideal_us = samples_per_block * 1_000_000 / sample_rate_hz
        self._block_dt_us = ideal_us * (1.0 + drift_ppm / 1_000_000.0)

    def _sample(self, global_i: int) -> list:
        """One sample row of ``channel_count`` int16 counts."""
        t = global_i / self.sample_rate_hz
        row = []
        for ch in range(self.channel_count):
            if ch == 2 and self.channel_count >= 3:
                # Z: gravity (~1g ≈ 16384 counts) plus a slow wobble.
                base = 16384 + 400 * math.sin(2 * math.pi * 0.7 * t)
            else:
                # X/Y (and extra channels): tones at distinct frequencies.
                freq = 5.0 + 3.0 * ch
                base = 1500 * math.sin(2 * math.pi * freq * t + ch)
            noise = self._rng.uniform(-self.noise_counts, self.noise_counts)
            row.append(_clip16(base + noise))
        return row

    def next_frame(self) -> Optional[bytes]:
        if self.max_packets is not None and self._emitted >= self.max_packets:
            return None

        # Emit a liveness beacon every `heartbeat_every` data blocks. It consumes a seq
        # (so beacons share the data stream's gap detection) but carries no samples and
        # does not count against the data-packet budget.
        if self.heartbeat_every and self._blocks_since_hb >= self.heartbeat_every:
            self._blocks_since_hb = 0
            frame = encode_heartbeat(
                node_id=self.node_id,
                seq=self._seq,
                t_node_us=self._t_node_us,
                sample_rate_hz=self.sample_rate_hz,
            )
            self._seq = (self._seq + 1) & 0xFFFFFFFF
            return frame

        samples = []
        for _ in range(self.samples_per_block):
            samples.append(self._sample(self._sample_index))
            self._sample_index += 1

        frame = encode_sample_block(
            node_id=self.node_id,
            seq=self._seq,
            t_node_us=self._t_node_us,
            sample_rate_hz=self.sample_rate_hz,
            channel_count=self.channel_count,
            samples=samples,
        )

        self._seq = (self._seq + 1) & 0xFFFFFFFF
        self._t_node_us = (self._t_node_us + round(self._block_dt_us)) & 0xFFFFFFFFFFFFFFFF
        self._emitted += 1
        self._blocks_since_hb += 1
        return frame
