"""
WireDAQ time source — the fifth port (the controllable clock).

Borrowed straight from how a desktop RTOS test harness (e.g. mbed-benchtest's RTXOff)
keeps firmware testable: separate *what* happens from *when* it happens by putting time
behind an interface you control. Real links add latency and jitter; nodes drift; a node
that goes silent must eventually be declared lost. None of that is testable
deterministically if the code reads the wall clock directly.

So every WireDAQ component that cares about time reads it from a :class:`Clock`:

  * :class:`WallClock` — real monotonic time, for live runs against real hardware.
  * :class:`SimClock`  — virtual time the test advances by hand, so a one-second timeout
    or a 200 ms link delay is exercised in microseconds of real time, with byte-for-byte
    reproducible results.

All times are **integer microseconds**, matching the wire format's ``t_node_us`` field so
node time and simulator time share one unit.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod


class Clock(ABC):
    """A monotonic source of time in integer microseconds."""

    @abstractmethod
    def now_us(self) -> int:
        """Return the current time in microseconds (monotonic, non-decreasing)."""


class WallClock(Clock):
    """Real monotonic time. Use in live runs; never goes backwards."""

    def __init__(self) -> None:
        self._t0 = time.monotonic_ns()

    def now_us(self) -> int:
        return (time.monotonic_ns() - self._t0) // 1000


class SimClock(Clock):
    """Virtual time under the test's control.

    Time only moves when you call :meth:`advance` (or :meth:`set_to`), so a simulated
    run is fully deterministic — the same script always produces the same timeline. This
    is what lets latency, jitter, and liveness timeouts be tested without real waiting.
    """

    def __init__(self, start_us: int = 0) -> None:
        self._now = int(start_us)

    def now_us(self) -> int:
        return self._now

    def advance(self, delta_us: int) -> int:
        """Move time forward by ``delta_us`` (must be >= 0). Returns the new time."""
        if delta_us < 0:
            raise ValueError("SimClock cannot go backwards")
        self._now += int(delta_us)
        return self._now

    def set_to(self, t_us: int) -> int:
        """Jump to an absolute time (must be >= current; clocks are monotonic)."""
        t_us = int(t_us)
        if t_us < self._now:
            raise ValueError("SimClock cannot go backwards")
        self._now = t_us
        return self._now
