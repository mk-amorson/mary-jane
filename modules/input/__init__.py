"""Shared input module — re-exports from sendinput."""

from modules.input.sendinput import (
    SC_SPACE, SC_A, SC_D,
    VK_BACK, VK_TAB, VK_SHIFT,
    key_down, key_up, tap_key, tap_vk, type_text, click_at,
    set_hwnd, get_hwnd, gamepad_release,
)
