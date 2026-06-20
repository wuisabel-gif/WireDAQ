"""
ImpairmentTransport — the "honest fake" (ADR 0001).

A decorator that wraps *any* :class:`Transport` and injects the things a real link does
to packets: **loss**, **duplication**, **reordering**, and **corruption**. Its whole
reason to exist is so the Collector's loss-and-jitter handling is exercised from Phase 1
— not discovered at Phase 4 when the first real board shows up. A simulator that never
drops a packet is a liability.

All randomness comes from a seeded ``random.Random`` so a run is exactly reproducible:
the same seed + config always produces the same impairment pattern, which makes the
pipeline testable (see ``tests/test_pipeline.py``).
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from typing import Optional

from tools.daq_sim.core.interfaces import Transport


@dataclass
class ImpairmentConfig:
    """Per-frame impairment probabilities (each in [0.0, 1.0])."""

    loss: float = 0.0        # drop the frame entirely (UDP datagram loss)
    duplicate: float = 0.0   # deliver the frame twice
    reorder: float = 0.0     # hold the frame back one slot so a later one overtakes it
    corrupt: float = 0.0     # flip a byte in the payload (CRC should catch it)

    def __post_init__(self) -> None:
        for name in ("loss", "duplicate", "reorder", "corrupt"):
            p = getattr(self, name)
            if not (0.0 <= p <= 1.0):
                raise ValueError(f"{name} probability must be in [0, 1], got {p}")


@dataclass
class ImpairmentStats:
    """Counters of what the link actually did — surfaced in the run summary."""

    offered: int = 0      # frames handed to send()
    delivered: int = 0    # frames actually placed on the inner transport
    dropped: int = 0      # frames lost
    duplicated: int = 0   # extra copies emitted
    reordered: int = 0    # frames whose delivery order was swapped
    corrupted: int = 0    # frames whose bytes were flipped


class ImpairmentTransport(Transport):
    """Wraps an inner transport and perturbs frames on the way through.

    Impairment is applied on :meth:`send`; :meth:`recv` simply delegates to the inner
    transport, so the receiver sees only the perturbed stream. Reordering uses a
    one-deep hold-back buffer: a held frame is released *after* the next frame, so the
    two swap places on the wire.
    """

    def __init__(
        self,
        inner: Transport,
        config: Optional[ImpairmentConfig] = None,
        seed: int = 0,
    ) -> None:
        self.inner = inner
        self.config = config or ImpairmentConfig()
        self.stats = ImpairmentStats()
        self._rng = random.Random(seed)
        self._held: Optional[bytes] = None  # frame waiting to be overtaken (reorder)

    # -- internal helpers ------------------------------------------------------
    def _corrupt(self, frame: bytes) -> bytes:
        """Flip one bit in a payload byte (leaves magic/header length intact so the
        frame still parses far enough for the CRC check to reject it)."""
        if len(frame) <= 26:  # header(24) + crc(2): no payload to corrupt
            idx = self._rng.randrange(2, 24)  # avoid magic so it still frames
        else:
            idx = self._rng.randrange(24, len(frame) - 2)
        mutated = bytearray(frame)
        mutated[idx] ^= 1 << self._rng.randrange(8)
        return bytes(mutated)

    def _deliver(self, frame: bytes) -> None:
        """Push a frame to the inner transport, applying duplication/corruption."""
        out = frame
        if self._rng.random() < self.config.corrupt:
            out = self._corrupt(frame)
            self.stats.corrupted += 1
        self.inner.send(out)
        self.stats.delivered += 1
        if self._rng.random() < self.config.duplicate:
            self.inner.send(out)
            self.stats.delivered += 1
            self.stats.duplicated += 1

    # -- Transport port --------------------------------------------------------
    def send(self, frame: bytes) -> None:
        self.stats.offered += 1

        if self._rng.random() < self.config.loss:
            self.stats.dropped += 1
            return

        # Reorder: hold this frame back; it will be released after the next one.
        if self._held is None and self._rng.random() < self.config.reorder:
            self._held = bytes(frame)
            self.stats.reordered += 1
            return

        self._deliver(frame)

        if self._held is not None:
            held, self._held = self._held, None
            self._deliver(held)  # released late → overtaken by `frame`

    def recv(self) -> Optional[bytes]:
        return self.inner.recv()

    def flush(self) -> None:
        """Release any frame still held for reordering, without closing the link, so
        nothing is silently swallowed at end-of-stream."""
        if self._held is not None:
            held, self._held = self._held, None
            self._deliver(held)

    def close(self) -> None:
        self.flush()
        self.inner.close()
