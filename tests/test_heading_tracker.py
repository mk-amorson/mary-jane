"""Tests for HeadingTracker — EMA-based heading change detection."""

import pytest
from unittest.mock import MagicMock

from modules.fishing.memory import HeadingTracker


class FakeMem:
    """Minimal mock for GTA5Memory that returns scripted headings."""

    def __init__(self, headings):
        self._headings = iter(headings)

    @property
    def connected(self):
        return True

    def read_heading(self):
        try:
            return next(self._headings)
        except StopIteration:
            return None


def test_idle_no_direction():
    """Stable heading → no direction detected."""
    mem = FakeMem([90.0] * 20)
    ht = HeadingTracker(mem)
    for _ in range(20):
        d = ht.update()
    assert d is None
    assert not ht.moving


def test_right_direction():
    """Increasing heading → right."""
    headings = [0.0 + i * 2.0 for i in range(20)]
    mem = FakeMem(headings)
    ht = HeadingTracker(mem)
    dirs = [ht.update() for _ in range(20)]
    assert "right" in dirs


def test_left_direction():
    """Decreasing heading → left."""
    headings = [90.0 - i * 2.0 for i in range(20)]
    mem = FakeMem(headings)
    ht = HeadingTracker(mem)
    dirs = [ht.update() for _ in range(20)]
    assert "left" in dirs


def test_wrap_around():
    """Heading wrapping around 180/-180 boundary."""
    headings = [178.0, 179.0, 180.0, -179.0, -178.0, -177.0]
    mem = FakeMem(headings)
    ht = HeadingTracker(mem)
    dirs = [ht.update() for _ in range(6)]
    # Should detect rightward motion (increasing through wrap)
    assert any(d == "right" for d in dirs if d is not None)


def test_reset_clears_state():
    """reset() clears accumulated direction."""
    mem = FakeMem([0.0 + i * 3.0 for i in range(10)] + [30.0] * 40)
    ht = HeadingTracker(mem)
    for _ in range(10):
        ht.update()
    assert ht.moving
    ht.reset()
    assert not ht.moving
    assert ht._accum == 0.0


def test_none_heading_returns_last():
    """When read_heading returns None, keep last direction."""
    headings = [0.0 + i * 3.0 for i in range(10)] + [None, None, None]
    mem = FakeMem(headings)
    ht = HeadingTracker(mem)
    last = None
    for _ in range(13):
        d = ht.update()
        if d is not None:
            last = d
    # Should have detected a direction before None readings
    assert last == "right"
