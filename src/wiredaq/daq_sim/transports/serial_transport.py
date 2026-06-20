"""
Byte-stream serial transports — the Phase-4 link, modeled honestly.

A real UART / RS-485 line is a *byte stream*: it does not preserve frame boundaries, it
delivers bytes in whatever chunks the UART FIFO happens to hand over, and on a noisy bus
there is line noise between frames and the occasional corrupted byte. The receiver has to
cope with all of it. These adapters reproduce exactly that, so the
:class:`StreamReceiver`'s sync-word framing is exercised in software before any wire
exists — the honest-fake principle (ADR 0001) applied at the byte level.

* :class:`LoopbackSerialTransport` — a clean byte pipe whose ``recv`` returns at most
  ``max_read`` bytes at a time, so frames are routinely split across reads.
* :class:`NoisySerialTransport` — a decorator that injects line noise (random garbage
  bytes between frames) and flips bits, seeded for reproducibility.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from typing import Optional

from wiredaq.daq_sim.core.interfaces import ByteStreamTransport


class LoopbackSerialTransport(ByteStreamTransport):
    """A loss-free in-memory byte pipe with chunked reads.

    ``max_read`` caps how many bytes a single :meth:`recv` returns, simulating a finite
    UART FIFO — small values force the receiver to reassemble frames from fragments.
    """

    def __init__(self, max_read: int = 64) -> None:
        if max_read < 1:
            raise ValueError("max_read must be >= 1")
        self.max_read = max_read
        self._buf = bytearray()

    def send(self, data: bytes) -> None:
        self._buf += data

    def recv(self) -> bytes:
        if not self._buf:
            return b""
        n = min(self.max_read, len(self._buf))
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def __len__(self) -> int:
        return len(self._buf)


@dataclass
class SerialNoiseConfig:
    """Byte-level impairment for a serial line."""

    garbage_prob: float = 0.0      # chance, per send, of preceding it with line noise
    garbage_max: int = 8           # max length of an injected noise burst
    corrupt_prob: float = 0.0      # per-byte chance of a bit flip

    def __post_init__(self) -> None:
        for name in ("garbage_prob", "corrupt_prob"):
            p = getattr(self, name)
            if not (0.0 <= p <= 1.0):
                raise ValueError(f"{name} must be in [0, 1], got {p}")


@dataclass
class SerialNoiseStats:
    bytes_sent: int = 0
    garbage_injected: int = 0      # noise bytes inserted between frames
    bytes_corrupted: int = 0       # payload/header bytes whose bits were flipped


class NoisySerialTransport(ByteStreamTransport):
    """Wraps a byte-stream transport and adds line noise + bit flips on the way in."""

    def __init__(
        self,
        inner: ByteStreamTransport,
        config: Optional[SerialNoiseConfig] = None,
        seed: int = 0,
    ) -> None:
        self.inner = inner
        self.config = config or SerialNoiseConfig()
        self.stats = SerialNoiseStats()
        self._rng = random.Random(seed)

    def send(self, data: bytes) -> None:
        # Line noise before the frame (an inter-frame gap full of junk).
        if self.config.garbage_prob and self._rng.random() < self.config.garbage_prob:
            n = self._rng.randint(1, self.config.garbage_max)
            garbage = bytes(self._rng.randrange(256) for _ in range(n))
            self.stats.garbage_injected += n
            self.inner.send(garbage)

        # Per-byte corruption.
        if self.config.corrupt_prob:
            mutated = bytearray(data)
            for i in range(len(mutated)):
                if self._rng.random() < self.config.corrupt_prob:
                    mutated[i] ^= 1 << self._rng.randrange(8)
                    self.stats.bytes_corrupted += 1
            data = bytes(mutated)

        self.stats.bytes_sent += len(data)
        self.inner.send(data)

    def recv(self) -> bytes:
        return self.inner.recv()

    def close(self) -> None:
        self.inner.close()
