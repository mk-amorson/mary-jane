"""Hybrid input: PostMessage for taps/clicks, virtual gamepad for held keys.

PostMessage sends input to a window handle without affecting the physical
mouse/keyboard — used for taps (Space) and mouse clicks.

Virtual gamepad (ViGEmBus) for held directions (A/D during reel) —
works in background without window focus.
"""

import ctypes
import logging
import time

import vgamepad as vg

log = logging.getLogger(__name__)

user32 = ctypes.windll.user32

# DirectInput scan codes
SC_SPACE = 0x39
SC_A     = 0x1E
SC_D     = 0x20

# Virtual key codes
VK_BACK  = 0x08
VK_TAB   = 0x09
VK_SHIFT = 0x10

# Window messages
WM_KEYDOWN     = 0x0100
WM_KEYUP       = 0x0101
WM_CHAR        = 0x0102
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP   = 0x0202
WM_MOUSEMOVE   = 0x0200
MK_LBUTTON     = 0x0001

# MapVirtualKey mapping types
MAPVK_VSC_TO_VK = 1
MAPVK_VK_TO_VSC = 0


# ── Target window ──

_hwnd = 0


def set_hwnd(hwnd: int):
    """Set the target window handle for PostMessage input."""
    global _hwnd
    _hwnd = hwnd


def get_hwnd() -> int:
    return _hwnd


def _make_key_lparam(scan_code: int, *, up: bool = False) -> int:
    """Build lParam for WM_KEYDOWN / WM_KEYUP."""
    lp = 1 | (scan_code << 16)
    if up:
        lp |= (1 << 30) | (1 << 31)
    return lp


# ── Virtual gamepad (ViGEmBus) for held directions ──

_gamepad: vg.VX360Gamepad | None = None


def _ensure_gamepad() -> vg.VX360Gamepad:
    global _gamepad
    if _gamepad is None:
        _gamepad = vg.VX360Gamepad()
        log.info("Virtual gamepad created")
    return _gamepad


def gamepad_release():
    """Release all gamepad inputs."""
    if _gamepad is not None:
        _gamepad.left_joystick_float(0.0, 0.0)
        _gamepad.update()


def key_down(scan_code: int):
    """Hold direction via virtual gamepad left stick (inverted for fishing)."""
    pad = _ensure_gamepad()
    if scan_code == SC_A:
        pad.left_joystick_float(-1.0, 0.0)
    elif scan_code == SC_D:
        pad.left_joystick_float(1.0, 0.0)
    else:
        pad.left_joystick_float(0.0, 0.0)
    pad.update()


def key_up(scan_code: int):
    """Release virtual gamepad stick."""
    pad = _ensure_gamepad()
    pad.left_joystick_float(0.0, 0.0)
    pad.update()


# ── Keyboard: taps via PostMessage (no physical interference) ──

def tap_key(scan_code: int):
    vk = user32.MapVirtualKeyW(scan_code, MAPVK_VSC_TO_VK)
    user32.PostMessageW(_hwnd, WM_KEYDOWN, vk, _make_key_lparam(scan_code))
    time.sleep(0.03)
    user32.PostMessageW(_hwnd, WM_KEYUP, vk, _make_key_lparam(scan_code, up=True))


def tap_vk(vk_code: int):
    """Press and release a virtual key (e.g. VK_BACK = 0x08)."""
    sc = user32.MapVirtualKeyW(vk_code, MAPVK_VK_TO_VSC)
    user32.PostMessageW(_hwnd, WM_KEYDOWN, vk_code, _make_key_lparam(sc))
    time.sleep(0.03)
    user32.PostMessageW(_hwnd, WM_KEYUP, vk_code, _make_key_lparam(sc, up=True))


# ── Keyboard: text input via PostMessage ──

def type_text(text: str):
    """Type text via WM_CHAR messages."""
    for ch in text:
        code = ord(ch)
        user32.PostMessageW(_hwnd, WM_CHAR, code, 0)
        time.sleep(0.02)


# ── Mouse: clicks via PostMessage (no cursor movement) ──

def click_at(client_x: int, client_y: int):
    """Click at client-relative coordinates inside the target window."""
    lparam = (client_y << 16) | (client_x & 0xFFFF)
    user32.PostMessageW(_hwnd, WM_MOUSEMOVE, 0, lparam)
    time.sleep(0.03)
    user32.PostMessageW(_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.03)
    user32.PostMessageW(_hwnd, WM_LBUTTONUP, 0, lparam)
