"""
ImpairmentTransport — the "honest fake" (ADR 0001).

A decorator that wraps *any* :class:`Transport` and injects the things a real link does
to packets: **loss**, **duplication**, **reordering**, **corruption**, and **latency with
jitter**. Its whole reason to exist is so the Collector's loss-and-jitter handling is
exercised from Phase 1 — not discovered at Phase 4 when the first real board shows up. A
simulator that never drops a packet is a liability.

Latency is the one impairment a real link *always* has, so it is modelled in time, not
just probability: every frame is held for ``delay_us`` ± ``jitter_us`` before it becomes
visible on the inner transport. Timing is read from a :class:`Clock` (the same port nodes
and liveness use), so a 200 ms link delay is simulated in microseconds of real time and is
exactly reproducible. When jitter exceeds the spacing between sends, frames overtake each
other on their own — the honest, emergent form of reordering — on top of the discrete
``reorder`` knob.

All randomness comes from a seeded ``random.Random`` so a run is exactly reproducible: the
same seed + config always produces the same impairment pattern, which makes the pipeline
testable (see ``tests/test_pipeline.py``).
"""

from __future__ import annotations

import heapq
import itertools
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from wiredaq.daq_sim.core.clock import Clock, WallClock
from wiredaq.daq_sim.core.interfaces import Transport


@dataclass
class ImpairmentConfig:
    """Per-frame impairment knobs.

    The four ``*`` probabilities are each in [0.0, 1.0]. ``delay_us`` / ``jitter_us`` are a
    timing model: the baseline one-way link delay and its random spread, in microseconds.
    """

    loss: float = 0.0        # drop the frame entirely (UDP datagram loss)
    duplicate: float = 0.0   # deliver the frame twice
    reorder: float = 0.0     # hold the frame back one slot so a later one overtakes it
    corrupt: float = 0.0     # flip a byte in the payload (CRC should catch it)
    delay_us: int = 0        # baseline one-way latency before a frame is visible
    jitter_us: int = 0       # +/- uniform spread on the delay (causes natural reordering)

    def __post_init__(self) -> None:
        for name in ("loss", "duplicate", "reorder", "corrupt"):
            p = getattr(self, name)
            if not (0.0 <= p <= 1.0):
                raise ValueError(f"{name} probability must be in [0, 1], got {p}")
        if self.delay_us < 0:
            raise ValueError(f"delay_us must be >= 0, got {self.delay_us}")
        if self.jitter_us < 0:
            raise ValueError(f"jitter_us must be >= 0, got {self.jitter_us}")

    @property
    def timed(self) -> bool:
        """True if any latency model is active (and the clock is therefore consulted)."""
        return self.delay_us > 0 or self.jitter_us > 0


@dataclass
class ImpairmentStats:
    """Counters of what the link actually did — surfaced in the run summary."""

    offered: int = 0       # frames handed to send()
    delivered: int = 0     # frames actually placed on the inner transport
    dropped: int = 0       # frames lost
    duplicated: int = 0    # extra copies emitted
    reordered: int = 0     # frames whose delivery order was swapped (discrete knob)
    corrupted: int = 0     # frames whose bytes were flipped
    delayed: int = 0       # frames that passed through the latency buffer
    max_delay_us: int = 0  # largest delay actually applied to any frame


class ImpairmentTransport(Transport):
    """Wraps an inner transport and perturbs frames on the way through.

    Impairment is applied on :meth:`send`; :meth:`recv` releases any frames whose latency
    has elapsed (per the :class:`Clock`) and then delegates to the inner transport, so the
    receiver sees only the perturbed stream. The discrete ``reorder`` knob uses a one-deep
    hold-back buffer (a held frame is released *after* the next one, swapping the two);
    latency uses a time-ordered release buffer keyed on the clock.
    """

    def __init__(
        self,
        inner: Transport,
        config: Optional[ImpairmentConfig] = None,
        seed: int = 0,
        clock: Optional[Clock] = None,
    ) -> None:
        self.inner = inner
        self.config = config or ImpairmentConfig()
        self.stats = ImpairmentStats()
        self.clock = clock or WallClock()
        self._rng = random.Random(seed)
        self._held: Optional[bytes] = None  # frame waiting to be overtaken (reorder)
        # Min-heap of (release_us, tiebreak, frame) for the latency model.
        self._scheduled: List[Tuple[int, int, bytes]] = []
        self._seq = itertools.count()  # stable tiebreak → FIFO among equal release times

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

    def _push_inner(self, frame: bytes) -> None:
        """Place one frame on the inner transport and count it as delivered."""
        self.inner.send(frame)
        self.stats.delivered += 1

    def _schedule(self, frame: bytes) -> None:
        """Deliver now, or hold for ``delay_us`` ± ``jitter_us`` if a latency model is on."""
        if not self.config.timed:
            self._push_inner(frame)
            return
        delay = self.config.delay_us
        if self.config.jitter_us:
            delay += self._rng.randint(-self.config.jitter_us, self.config.jitter_us)
        delay = max(0, delay)
        release_us = self.clock.now_us() + delay
        heapq.heappush(self._scheduled, (release_us, next(self._seq), frame))
        self.stats.delayed += 1
        if delay > self.stats.max_delay_us:
            self.stats.max_delay_us = delay

    def _emit(self, frame: bytes) -> None:
        """Apply corruption/duplication, then schedule the resulting frame(s)."""
        out = frame
        if self._rng.random() < self.config.corrupt:
            out = self._corrupt(frame)
            self.stats.corrupted += 1
        self._schedule(out)
        if self._rng.random() < self.config.duplicate:
            self.stats.duplicated += 1
            self._schedule(out)

    def _release_due(self) -> None:
        """Move every frame whose release time has arrived onto the inner transport."""
        now = self.clock.now_us()
        while self._scheduled and self._scheduled[0][0] <= now:
            _, _, frame = heapq.heappop(self._scheduled)
            self._push_inner(frame)

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

        self._emit(frame)

        if self._held is not None:
            held, self._held = self._held, None
            self._emit(held)  # released late → overtaken by `frame`

    def recv(self) -> Optional[bytes]:
        if self.config.timed:
            self._release_due()
        return self.inner.recv()

    def flush(self) -> None:
        """Release the one-deep reorder hold *and* every frame still in the latency
        buffer, regardless of the clock, so nothing is silently swallowed at
        end-of-stream. Does not close the inner link."""
        if self._held is not None:
            held, self._held = self._held, None
            self._emit(held)
        while self._scheduled:
            _, _, frame = heapq.heappop(self._scheduled)
            self._push_inner(frame)

    def close(self) -> None:
        self.flush()
        self.inner.close()
