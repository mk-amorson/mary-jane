"""Tests for queue monitor helpers — OCR regions and ETA calculation."""

import pytest
from unittest.mock import MagicMock

from modules.queue_monitor import calc_number_region, ocr_digits, _update_eta, _reset_eta


class FakeState:
    def __init__(self):
        self.queue_eta_seconds = None
        self.queue_progress = 0.0
        self.queue_max_position = 0
        self.queue_rate = 0.0
        self.queue_prev_pos = None
        self.queue_prev_time = 0.0


def test_calc_number_region_basic():
    """Number region is placed right of text bbox."""
    text_bbox = (100, 200, 300, 40)
    img_size = (1920, 1080)
    nx, ny, nw, nh = calc_number_region(text_bbox, img_size)
    assert nx == 400  # tx + tw
    assert ny < 200   # expanded upward
    assert nh > 40    # expanded height
    assert nw > 0


def test_calc_number_region_clamps():
    """Region clamped to image bounds."""
    text_bbox = (1800, 50, 200, 30)
    img_size = (1920, 1080)
    nx, ny, nw, nh = calc_number_region(text_bbox, img_size)
    assert nx + nw <= 1920
    assert ny >= 0


def test_update_eta_first_reading():
    """First reading sets prev values but no rate yet."""
    state = FakeState()
    _update_eta(state, 100)
    assert state.queue_prev_pos == 100
    assert state.queue_max_position == 100
    assert state.queue_rate == 0.0
    assert state.queue_eta_seconds is None


def test_update_eta_decreasing():
    """Decreasing position → positive rate → ETA calculated."""
    import time
    state = FakeState()
    _update_eta(state, 100)
    # Simulate time passing
    state.queue_prev_time = time.monotonic() - 10.0  # 10 seconds ago
    _update_eta(state, 90)
    assert state.queue_rate > 0
    assert state.queue_eta_seconds is not None
    assert state.queue_eta_seconds > 0


def test_update_eta_outlier_rejected():
    """Jump > 30 positions is rejected."""
    state = FakeState()
    _update_eta(state, 100)
    _update_eta(state, 50)  # jump of 50 > MAX_JUMP of 30
    assert state.queue_prev_pos == 100  # not updated


def test_update_eta_progress():
    """Progress tracks proportion from max."""
    import time
    state = FakeState()
    _update_eta(state, 100)
    state.queue_prev_time = time.monotonic() - 5.0
    _update_eta(state, 80)
    assert state.queue_max_position == 100
    assert state.queue_progress == pytest.approx(0.2, abs=0.01)


def test_reset_eta():
    """reset_eta clears all ETA state."""
    state = FakeState()
    state.queue_eta_seconds = 42.0
    state.queue_rate = 1.5
    state.queue_max_position = 100
    _reset_eta(state)
    assert state.queue_eta_seconds is None
    assert state.queue_rate == 0.0
    assert state.queue_max_position == 0
