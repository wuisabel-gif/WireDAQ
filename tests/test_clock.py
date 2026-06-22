"""Tests for the Clock port (SimClock / WallClock)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from wiredaq.daq_sim.core.clock import SimClock, WallClock  # noqa: E402


def test_simclock_starts_and_advances():
    c = SimClock()
    assert c.now_us() == 0
    assert c.advance(100) == 100
    assert c.now_us() == 100
    c.advance(0)  # zero advance is allowed (no time passes)
    assert c.now_us() == 100


def test_simclock_start_offset_and_set_to():
    c = SimClock(start_us=1_000)
    assert c.now_us() == 1_000
    assert c.set_to(5_000) == 5_000
    assert c.now_us() == 5_000


def test_simclock_is_monotonic():
    c = SimClock(start_us=10)
    with pytest.raises(ValueError):
        c.advance(-1)
    with pytest.raises(ValueError):
        c.set_to(9)  # earlier than current → rejected


def test_wallclock_nonnegative_and_nondecreasing():
    c = WallClock()
    a = c.now_us()
    b = c.now_us()
    assert a >= 0
    assert b >= a  # monotonic
