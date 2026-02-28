"""Tests for ApiClient — refresh lock, session management."""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from api_client import ApiClient
from auth.token_store import TokenStore


def test_refresh_lock_exists():
    """ApiClient should have a refresh lock to prevent parallel refreshes."""
    ts = MagicMock(spec=TokenStore)
    ts.access_token = "test"
    ts.refresh_token = "test_refresh"
    client = ApiClient("http://localhost:8000", ts)
    assert hasattr(client, '_refresh_lock')
    assert isinstance(client._refresh_lock, asyncio.Lock)


def test_server_url_trailing_slash():
    """Trailing slash is stripped from server URL."""
    ts = MagicMock(spec=TokenStore)
    client = ApiClient("http://localhost:8000/", ts)
    assert client._base == "http://localhost:8000"
