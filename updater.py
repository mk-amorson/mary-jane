"""Auto-updater: check server for new version, download & replace .exe."""

import os
import sys
import logging
import tempfile
import subprocess

import aiohttp

from version import __version__

log = logging.getLogger(__name__)


def _is_frozen() -> bool:
    return getattr(sys, 'frozen', False)


def _current_exe() -> str:
    return sys.executable if _is_frozen() else ""


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse '1.2.3' → (1, 2, 3)."""
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except (ValueError, AttributeError):
        return (0,)


def is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


async def check_update(api_client) -> dict | None:
    """GET /app/version → {version, download_url, ...} or None if up to date."""
    try:
        resp = await api_client.get_app_version()
        if resp is None:
            return None
        remote_ver = resp.get("version")
        if not remote_ver:
            return None
        if is_newer(remote_ver, __version__):
            log.info("Update available: %s → %s", __version__, remote_ver)
            return resp
        return None
    except Exception:
        log.debug("Update check failed", exc_info=True)
        return None


async def download_update(url: str, dest: str, progress_cb=None) -> bool:
    """Download file from url to dest. Returns True on success."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    log.error("Download failed: HTTP %d", resp.status)
                    return False
                total = resp.content_length or 0
                downloaded = 0
                with open(dest, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb and total > 0:
                            progress_cb(downloaded / total)
        log.info("Downloaded update to %s (%d bytes)", dest, downloaded)
        return True
    except Exception:
        log.exception("Download failed")
        return False


def apply_update(new_exe: str) -> None:
    """Write update.bat, launch it, exit current process."""
    current = _current_exe()
    if not current:
        log.error("Cannot apply update: not running as frozen .exe")
        return

    bat_content = (
        '@echo off\r\n'
        'timeout /t 2 /nobreak >nul\r\n'
        'del "%~1"\r\n'
        'move "%~2" "%~1"\r\n'
        'start "" "%~1"\r\n'
        'del "%~f0"\r\n'
    )

    bat_path = os.path.join(os.path.dirname(current), "update.bat")
    with open(bat_path, 'w') as f:
        f.write(bat_content)

    subprocess.Popen(
        ['cmd', '/c', bat_path, current, new_exe],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    sys.exit(0)
