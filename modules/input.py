"""Shared low-level input module — keyboard & mouse via SendInput.

Used by fishing bot, sell automation, and future bots.
"""

import ctypes
import time

user32 = ctypes.windll.user32

# DirectInput scan codes
SC_SPACE = 0x39
SC_A     = 0x1E
SC_D     = 0x20

# Virtual key codes
VK_BACK  = 0x08
VK_TAB   = 0x09
VK_SHIFT = 0x10

# SendInput constants
INPUT_KEYBOARD = 1
INPUT_MOUSE    = 0
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP    = 0x0002
KEYEVENTF_UNICODE  = 0x0004
MOUSEEVENTF_MOVE     = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP   = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


# ── Keyboard: scan-code (DirectInput) ──

def key_down(scan_code: int):
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = _KEYBDINPUT(wVk=0, wScan=scan_code, dwFlags=KEYEVENTF_SCANCODE, time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def key_up(scan_code: int):
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = _KEYBDINPUT(wVk=0, wScan=scan_code, dwFlags=KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def tap_key(scan_code: int):
    key_down(scan_code)
    time.sleep(0.03)
    key_up(scan_code)


# ── Keyboard: virtual-key (for UI elements like Backspace, Tab) ──

def tap_vk(vk_code: int):
    """Press and release a virtual key (e.g. VK_BACK = 0x08)."""
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = _KEYBDINPUT(wVk=vk_code, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    time.sleep(0.03)
    inp2 = _INPUT(type=INPUT_KEYBOARD)
    inp2.u.ki = _KEYBDINPUT(wVk=vk_code, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(inp2), ctypes.sizeof(inp2))


# ── Keyboard: text input ──

def type_text(text: str):
    """Type text: VK codes for ASCII printable chars, KEYEVENTF_UNICODE for Cyrillic etc."""
    for ch in text:
        code = ord(ch)
        if 0x20 <= code <= 0x7E:
            # ASCII printable — map to virtual key via VkKeyScanW
            vk_result = user32.VkKeyScanW(code)
            if vk_result == -1:
                # VkKeyScanW failed — fall back to Unicode
                _type_unicode_char(code)
                continue
            vk = vk_result & 0xFF
            shift = (vk_result >> 8) & 0x01
            if shift:
                _vk_down(VK_SHIFT)
                time.sleep(0.01)
            tap_vk(vk)
            if shift:
                _vk_up(VK_SHIFT)
            time.sleep(0.02)
        else:
            _type_unicode_char(code)


def _vk_down(vk: int):
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _vk_up(vk: int):
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _type_unicode_char(code: int):
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = _KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    time.sleep(0.02)
    inp2 = _INPUT(type=INPUT_KEYBOARD)
    inp2.u.ki = _KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(inp2), ctypes.sizeof(inp2))
    time.sleep(0.02)


# ── Mouse ──

def click_at(screen_x: int, screen_y: int):
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    abs_x = screen_x * 65536 // sw
    abs_y = screen_y * 65536 // sh

    inp = _INPUT(type=INPUT_MOUSE)
    inp.u.mi = _MOUSEINPUT(dx=abs_x, dy=abs_y, mouseData=0,
                            dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
                            time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    time.sleep(0.03)

    inp2 = _INPUT(type=INPUT_MOUSE)
    inp2.u.mi = _MOUSEINPUT(dx=abs_x, dy=abs_y, mouseData=0,
                             dwFlags=MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE,
                             time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(inp2), ctypes.sizeof(inp2))

    time.sleep(0.03)

    inp3 = _INPUT(type=INPUT_MOUSE)
    inp3.u.mi = _MOUSEINPUT(dx=abs_x, dy=abs_y, mouseData=0,
                             dwFlags=MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE,
                             time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(inp3), ctypes.sizeof(inp3))
