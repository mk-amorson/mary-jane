import os
import sys


def resource_path(relative: str) -> str:
    """Resolve path to bundled resource (works both in dev and PyInstaller .exe)."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def app_dir() -> str:
    """Directory where the app is installed (not the temp _MEIPASS)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))
