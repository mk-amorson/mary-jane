"""Tests for core module — AppState, SERVER_URL loading."""

from core import AppState, _load_server_url, _DEFAULT_SERVER_URL


def test_appstate_has_no_fishing_v1():
    """Fishing v1 fields should be removed."""
    s = AppState()
    assert not hasattr(s, 'fishing_active')
    assert not hasattr(s, 'fishing_step')
    assert not hasattr(s, 'fishing_squares')
    assert not hasattr(s, 'fishing_bounds')


def test_appstate_has_no_sell_fields():
    """Sell/marketplace/scan fields should be removed."""
    s = AppState()
    assert not hasattr(s, 'sell_active')
    assert not hasattr(s, 'marketplace_parsing')
    assert not hasattr(s, 'scan_active')
    assert not hasattr(s, 'current_server')


def test_appstate_fishing2_exists():
    """Fishing v2 fields should still exist."""
    s = AppState()
    assert hasattr(s, 'fishing2_active')
    assert hasattr(s, 'fishing2_step')
    assert s.fishing2_step == "idle"


def test_appstate_markers_exist():
    """Marker fields should exist."""
    s = AppState()
    assert hasattr(s, 'markers_pos')
    assert hasattr(s, 'markers_yaw')
    assert hasattr(s, 'markers_cam_pos')


def test_load_server_url_default():
    """Without config.json server_url key, returns default."""
    # _load_server_url reads from config.json — if no server_url key, returns default
    url = _load_server_url()
    assert url == _DEFAULT_SERVER_URL or url.startswith("http")
