"""Shared game interaction helpers — frame grabbing, template matching, OCR.

Used by sell/automation.py and price_scan/automation.py.
"""

import os
import re
import asyncio
import logging

import cv2
import numpy as np
import pytesseract

from core import get_game_rect
from utils import resource_path
from modules.input import click_at, tap_vk, type_text, VK_BACK, _vk_down, _vk_up
from modules.sell.detector import _normalize, _preprocess

log = logging.getLogger(__name__)

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ── Templates ──

_REF_DIR = resource_path("reference")
_TEMPLATES = {}


def _get_template(name: str):
    if name not in _TEMPLATES:
        path = os.path.join(_REF_DIR, f"{name}.png")
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            log.error("Template not found: %s", path)
        _TEMPLATES[name] = img
    return _TEMPLATES[name]


# ── Frame acquisition ──

async def grab_frame(state, timeout=3.0):
    """Get a frame from provider, restarting if needed."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not state.frame_provider.running:
            state.frame_provider.start()
            await asyncio.sleep(0.5)
            continue
        img = state.frame_provider.get_image()
        if img is not None:
            return img
        await asyncio.sleep(0.1)
    log.warning("grab_frame timed out after %.1fs", timeout)
    return None


# ── Template matching ──

def find_template(frame_np, tmpl, threshold=0.7):
    """Match template in frame. Returns (cx, cy, x, y, w, h) or None."""
    if tmpl is None or frame_np is None:
        return None
    gray = cv2.cvtColor(frame_np, cv2.COLOR_RGB2GRAY) if len(frame_np.shape) == 3 else frame_np
    res = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < threshold:
        return None
    th, tw = tmpl.shape[:2]
    cx = max_loc[0] + tw // 2
    cy = max_loc[1] + th // 2
    return (cx, cy, max_loc[0], max_loc[1], tw, th)


async def find_and_click(state, tmpl_name, threshold=0.7, retries=3):
    """Grab frame, find template, click at game coordinates. Retries on failure."""
    tmpl = _get_template(tmpl_name)
    for attempt in range(retries):
        img = await grab_frame(state)
        if img is None:
            log.warning("find_and_click('%s') — no frame (attempt %d)", tmpl_name, attempt + 1)
            await asyncio.sleep(0.5)
            continue
        frame_np = np.array(img)
        hit = find_template(frame_np, tmpl, threshold)
        if hit is None:
            log.info("template '%s' not found (attempt %d/%d)", tmpl_name, attempt + 1, retries)
            await asyncio.sleep(0.5)
            continue
        cx, cy, rx, ry, rw, rh = hit
        # store for overlay visualization
        state.sell_match_rect = (rx, ry, rw, rh)
        state.sell_match_name = tmpl_name
        gr = state.game_rect
        if gr is None:
            log.warning("find_and_click('%s') — game_rect is None", tmpl_name)
            return False
        gx, gy = gr[0], gr[1]
        click_at(gx + cx, gy + cy)
        log.info("clicked '%s' at (%d, %d)", tmpl_name, gx + cx, gy + cy)
        return True
    log.warning("template '%s' not found after %d retries", tmpl_name, retries)
    return False


# ── OCR helpers ──

async def ocr_min_price(state):
    """OCR marketplace screen for 'Цена от:' → int price."""
    img = await grab_frame(state)
    if img is None:
        return None
    w, h = img.size
    crop = img.crop((int(w * 0.12), int(h * 0.04), int(w * 0.88), int(h * 0.95)))
    processed = _preprocess(crop)
    try:
        text = pytesseract.image_to_string(processed, lang="rus+eng", config="--oem 3 --psm 6")
    except Exception:
        log.exception("ocr_min_price: pytesseract failed")
        return None
    log.info("ocr_min_price text: %s", text[:200])
    m = re.search(r"[Цц]ена\s*(?:от|or|оr|oт)[:\s]*\$?\s*([\d\s]+)", text)
    if m is None:
        return None
    num_str = m.group(1).replace(" ", "").strip()
    if not num_str.isdigit():
        return None
    price = int(num_str)
    log.info("ocr_min_price: %d", price)
    return price


async def find_item_name_on_screen(state, name):
    """Find item name via OCR and click on it."""
    img = await grab_frame(state)
    if img is None:
        return False
    w, h = img.size
    x1, y1 = int(w * 0.12), int(h * 0.04)
    x2, y2 = int(w * 0.88), int(h * 0.95)
    crop = img.crop((x1, y1, x2, y2))
    processed = _preprocess(crop)
    try:
        data = pytesseract.image_to_data(
            processed, lang="rus+eng", output_type=pytesseract.Output.DICT,
            config="--oem 3 --psm 6",
        )
    except Exception:
        log.exception("find_item_name_on_screen: pytesseract failed")
        return False

    norm_name = _normalize(name)
    words = norm_name.split()
    if not words:
        return False

    n = len(data["text"])
    for i in range(n):
        txt = data["text"][i].strip()
        if not txt:
            continue
        if _normalize(txt) != words[0]:
            continue
        match = True
        for j, target in enumerate(words[1:], 1):
            if i + j >= n or _normalize(data["text"][i + j].strip()) != target:
                match = False
                break
        if not match:
            continue
        all_x, all_y = [], []
        for j in range(len(words)):
            idx = i + j
            all_x.append(data["left"][idx] + data["width"][idx] / 2)
            all_y.append(data["top"][idx] + data["height"][idx] / 2)
        cx = int(sum(all_x) / len(all_x))
        cy = int(sum(all_y) / len(all_y))
        gr = state.game_rect
        if gr is None:
            return False
        state.sell_item_click = (x1 + cx, y1 + cy)
        state.sell_match_name = "item_name"
        click_at(gr[0] + x1 + cx, gr[1] + y1 + cy)
        log.info("clicked item '%s' at (%d, %d)", name, gr[0] + x1 + cx, gr[1] + y1 + cy)
        return True

    log.info("item '%s' not found on screen", name)
    return False


# ── Async sleep with stop check ──

async def wait_active(state, seconds=1.0, active_attr="sell_active"):
    """Sleep in 0.1s increments, return False if active flag was cleared."""
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not getattr(state, active_attr, False):
            return False
        await asyncio.sleep(0.1)
    return True


def clear_overlay(state):
    """Reset overlay fields between steps."""
    state.sell_match_rect = None
    state.sell_match_name = ""
    state.sell_item_click = None
