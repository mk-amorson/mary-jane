"""Hybrid input: PostMessage for taps/clicks, virtual gamepad for held keys.

PostMessage sends input to a window handle without affecting the physical
mouse/keyboard — used for taps (Space) and mouse clicks.

Virtual gamepad (ViGEmBus) for held directions (A/D during reel) —
works in background without window focus.
"""

import ctypes
import logging
import time

try:
    import vgamepad as vg
    _HAS_VGAMEPAD = True
except Exception:
    _HAS_VGAMEPAD = False

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

_gamepad = None


def _ensure_gamepad():
    global _gamepad
    if _gamepad is None:
        if not _HAS_VGAMEPAD:
            log.warning("vgamepad not available — install ViGEmBus for background reel")
            return None
        try:
            _gamepad = vg.VX360Gamepad()
            log.info("Virtual gamepad created")
        except Exception as e:
            log.warning("Failed to create virtual gamepad (ViGEmBus installed?): %s", e)
            return None
    return _gamepad


def gamepad_release():
    """Release all gamepad inputs."""
    if _gamepad is not None:
        _gamepad.left_joystick_float(0.0, 0.0)
        _gamepad.update()


def key_down(scan_code: int):
    """Hold direction via virtual gamepad left stick."""
    pad = _ensure_gamepad()
    if pad is None:
        return
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
    if pad is None:
        return
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


# ── Mouse drag via PostMessage (no physical cursor movement) ──

def mouse_down_at(client_x: int, client_y: int):
    """Press left button at position (no release)."""
    lparam = (client_y << 16) | (client_x & 0xFFFF)
    user32.PostMessageW(_hwnd, WM_MOUSEMOVE, 0, lparam)
    time.sleep(0.01)
    user32.PostMessageW(_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)


def mouse_move_at(client_x: int, client_y: int):
    """Move mouse while button held (drag)."""
    lparam = (client_y << 16) | (client_x & 0xFFFF)
    user32.PostMessageW(_hwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam)


def mouse_up_at(client_x: int, client_y: int):
    """Release left button."""
    lparam = (client_y << 16) | (client_x & 0xFFFF)
    user32.PostMessageW(_hwnd, WM_LBUTTONUP, 0, lparam)


# ── Mouse drag via SendInput (moves physical cursor, works with all games) ──

class _INPUT_MOUSE(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _INPUT_MOUSE)]
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("u", _U),
    ]


_INPUT_MOUSE_TYPE = 0
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_ABSOLUTE = 0x8000

_SM_CXSCREEN = 0
_SM_CYSCREEN = 1


def _screen_size():
    # SM_CXVIRTUALSCREEN / SM_CYVIRTUALSCREEN for multi-monitor
    cx = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    cy = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    if cx == 0 or cy == 0:
        cx = user32.GetSystemMetrics(_SM_CXSCREEN)
        cy = user32.GetSystemMetrics(_SM_CYSCREEN)
    return cx, cy


def _to_absolute(screen_x, screen_y):
    """Convert screen pixel coords to SendInput absolute coords (0–65535)."""
    # Use virtual screen offset for multi-monitor
    vx = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    vy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    cx, cy = _screen_size()
    ax = int((screen_x - vx) * 65535 / cx)
    ay = int((screen_y - vy) * 65535 / cy)
    return ax, ay


def _send_mouse_input(flags, screen_x, screen_y):
    ax, ay = _to_absolute(screen_x, screen_y)
    inp = _INPUT()
    inp.type = _INPUT_MOUSE_TYPE
    inp.u.mi.dx = ax
    inp.u.mi.dy = ay
    inp.u.mi.dwFlags = flags | _MOUSEEVENTF_ABSOLUTE
    inp.u.mi.time = 0
    inp.u.mi.mouseData = 0
    inp.u.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def si_mouse_down(screen_x: int, screen_y: int):
    """SendInput: move cursor + press left button (screen coords)."""
    _send_mouse_input(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_LEFTDOWN, screen_x, screen_y)


def si_mouse_move(screen_x: int, screen_y: int):
    """SendInput: move cursor (screen coords). Use while button held for drag."""
    _send_mouse_input(_MOUSEEVENTF_MOVE, screen_x, screen_y)


def si_mouse_up(screen_x: int, screen_y: int):
    """SendInput: release left button (screen coords)."""
    _send_mouse_input(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_LEFTUP, screen_x, screen_y)
