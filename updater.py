"""Auto-updater: check server for new version, download & replace .exe."""

import os
import sys
import json
import logging
import subprocess
import urllib.request
import urllib.error

from version import __version__

log = logging.getLogger(__name__)


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse '1.2.3' → (1, 2, 3)."""
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except (ValueError, AttributeError):
        return (0,)


def is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def check_update_sync(server_url: str) -> dict | None:
    """GET /app/version (synchronous, 3s timeout).

    Returns dict if newer version available, None if up to date.
    Raises on network errors.
    """
    url = f"{server_url}/app/version"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=3) as resp:
        data = json.loads(resp.read().decode())
    remote_ver = data.get("version")
    if not remote_ver:
        return None
    if is_newer(remote_ver, __version__):
        log.info("Update available: %s → %s", __version__, remote_ver)
        return data
    return None


def download_update_sync(url: str, dest: str, progress_cb=None) -> bool:
    """Download file from url to dest (synchronous). Returns True on success."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, 'wb') as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
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
    if not getattr(sys, 'frozen', False):
        log.error("Cannot apply update: not running as frozen .exe")
        return

    current = sys.executable
    bat_content = (
        '@echo off\r\n'
        # Wait for old exe to fully exit and release _MEI temp dir
        ':wait\r\n'
        'timeout /t 2 /nobreak >nul\r\n'
        'del /Q "%~1" 2>nul\r\n'
        'if exist "%~1" goto wait\r\n'
        # Replace with new exe
        'move /Y "%~2" "%~1"\r\n'
        # Wait for filesystem to settle before launching
        'timeout /t 2 /nobreak >nul\r\n'
        'start "" "%~1"\r\n'
        'del /Q "%~f0"\r\n'
    )

    bat_path = os.path.join(os.path.dirname(current), "update.bat")
    with open(bat_path, 'w') as f:
        f.write(bat_content)

    subprocess.Popen(
        ['cmd', '/c', bat_path, current, new_exe],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    sys.exit(0)
