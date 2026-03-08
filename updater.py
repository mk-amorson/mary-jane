"""Auto-updater: check GitHub Releases for new version, download & replace .exe."""

import os
import sys
import json
import logging
import subprocess
import urllib.request
import urllib.error

from version import __version__

log = logging.getLogger(__name__)

GITHUB_REPO = "mk-amorson/mary-jane"
GITHUB_TOKEN = ""  # Fine-grained read-only token for private repo


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse '1.2.3' → (1, 2, 3)."""
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except (ValueError, AttributeError):
        return (0,)


def is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def check_update_sync() -> dict | None:
    """Check GitHub Releases for newer version. Returns dict or None."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())

    remote_ver = data.get("tag_name", "").lstrip("v")
    if not remote_ver or not is_newer(remote_ver, __version__):
        return None

    log.info("Update available: %s → %s", __version__, remote_ver)

    # Find .exe asset
    for asset in data.get("assets", []):
        if asset["name"].endswith(".exe"):
            return {
                "version": remote_ver,
                "download_url": asset["url"],  # API URL, needs Accept header
                "name": asset["name"],
            }
    return None


def download_update_sync(url: str, dest: str, progress_cb=None) -> bool:
    """Download release asset from GitHub (private repo needs auth)."""
    try:
        headers = {"Accept": "application/octet-stream"}
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

        req = urllib.request.Request(url, headers=headers)
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
