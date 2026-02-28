"""Tests for stash timer helpers."""

from ui.stash import stash_status, fmt_time


def test_fmt_time_minutes():
    assert fmt_time(90) == "01:30"
    assert fmt_time(0) == "00:00"
    assert fmt_time(59) == "00:59"


def test_fmt_time_hours():
    assert fmt_time(3661) == "1:01:01"
    assert fmt_time(7200) == "2:00:00"


def test_fmt_time_negative():
    """Negative values clamped to 0."""
    assert fmt_time(-10) == "00:00"


def test_stash_status_returns_tuple():
    """stash_status returns (is_open, seconds_remaining)."""
    hours = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23]
    is_open, secs = stash_status(hours, 15, 20)
    assert isinstance(is_open, bool)
    assert isinstance(secs, (int, float))
    assert secs >= 0


def test_stash_status_danger_zone():
    """Danger zone has 4-hour cycle."""
    hours = [2, 6, 10, 14, 18, 22]
    is_open, secs = stash_status(hours, 0, 5)
    assert isinstance(is_open, bool)
    # At most 4 hours until next opening
    assert secs <= 4 * 3600
