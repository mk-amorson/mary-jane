"""Toilet cleaning bot — template match + zigzag drag via PostMessage.

Finds toilet boundaries and brush (jorshik) on screen,
grabs the brush and drags it in a zigzag pattern across the toilet.
Each horizontal sweep takes 250ms, vertical step = screen_height / 20.
Mouse is held from grab until the entire toilet is cleaned.
"""
import asyncio
import logging
import os
import time

import cv2
import numpy as np

import win32gui
from core import GAME_WINDOW_TITLE, ensure_capture
from modules.input.sendinput import (
    si_mouse_down, si_mouse_move, si_mouse_up,
)
from utils import resource_path

log = logging.getLogger(__name__)

# ── Templates ──

_REF_DIR = resource_path(os.path.join("assets", "reference"))
_TOILET_PATH = os.path.join(_REF_DIR, "toilet.png")
_JORSHIK_PATH = os.path.join(_REF_DIR, "jorshik.png")

TOILET_TMPL = cv2.imread(_TOILET_PATH, cv2.IMREAD_GRAYSCALE)
JORSHIK_TMPL = cv2.imread(_JORSHIK_PATH, cv2.IMREAD_GRAYSCALE)

if TOILET_TMPL is not None:
    log.info("toilet.png loaded: %dx%d", TOILET_TMPL.shape[1], TOILET_TMPL.shape[0])
else:
    log.warning("toilet.png not found at %s", _TOILET_PATH)

if JORSHIK_TMPL is not None:
    log.info("jorshik.png loaded: %dx%d", JORSHIK_TMPL.shape[1], JORSHIK_TMPL.shape[0])
else:
    log.warning("jorshik.png not found at %s", _JORSHIK_PATH)


# ── Template matching (multi-scale) ──

def _find_template(frame_gray, tmpl, threshold=0.6, scales=None):
    """Multi-scale template match. Returns (x, y, w, h) or None."""
    if tmpl is None:
        return None
    if scales is None:
        scales = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    th, tw = tmpl.shape[:2]
    fh, fw = frame_gray.shape[:2]
    best_val = 0
    best_rect = None
    for s in scales:
        sw, sh = int(tw * s), int(th * s)
        if sw < 10 or sh < 10 or sw > fw or sh > fh:
            continue
        resized = cv2.resize(tmpl, (sw, sh))
        res = cv2.matchTemplate(frame_gray, resized, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(res)
        if mv > best_val:
            best_val = mv
            best_rect = (ml[0], ml[1], sw, sh)
    if best_val >= threshold:
        return best_rect
    return None


# ── Path builder ──

def _build_path(toilet_rect, screen_h):
    """Build zigzag path within toilet inner area.

    Includes smooth travel from current position to first sweep start,
    horizontal sweeps, and smooth vertical transitions.

    Returns list of (start_x, start_y, end_x, end_y, duration_s).
    """
    tx, ty, tw, th = toilet_rect
    mx = int(tw * 0.18)
    mt = int(th * 0.18)
    mb = int(th * 0.12)
    left = tx + mx
    right = tx + tw - mx
    top = ty + mt
    bottom = ty + th - mb

    step_y = max(1, screen_h // 20)
    sweep_dur = 0.25   # horizontal pass
    down_dur = 0.06    # smooth vertical step

    path = []
    y = top
    going_right = True

    while y < bottom:
        if going_right:
            path.append((left, y, right, y, sweep_dur))
        else:
            path.append((right, y, left, y, sweep_dur))

        next_y = min(y + step_y, bottom)
        if next_y > y:
            end_x = right if going_right else left
            path.append((end_x, y, end_x, next_y, down_dur))

        y = next_y
        going_right = not going_right

    return path


# ── Context ──

class _Ctx:
    def __init__(self):
        self.mouse_held = False
        self.path = []
        self.seg_idx = 0
        self.seg_start = 0.0
        self.last_x = 0
        self.last_y = 0
        self.screen_ox = 0
        self.screen_oy = 0


def _release(ctx):
    if ctx.mouse_held:
        si_mouse_up(ctx.last_x, ctx.last_y)
        ctx.mouse_held = False


def _reset(state, ctx):
    _release(ctx)
    ctx.path = []
    ctx.seg_idx = 0
    state.toilet_step = "idle"
    state.toilet_rect = None
    state.toilet_jorshik = None
    state.toilet_cursor = None
    state.toilet_path = None


# ── Main loop ──

async def toilet_bot_loop(state):
    log.info("Toilet bot loop started")
    ctx = _Ctx()

    while True:
        if not state.toilet_active:
            if state.toilet_step != "idle":
                log.info("Toilet bot deactivated → idle")
                _reset(state, ctx)
            await asyncio.sleep(0.2)
            continue

        # First activation
        if state.toilet_step == "idle":
            await ensure_capture(state)
            state.toilet_step = "search"
            log.info("Toilet bot: searching...")

        img = state.frame_provider.get_image()
        if img is None:
            await asyncio.sleep(0.1)
            continue

        frame_np = np.array(img)
        fh, fw = frame_np.shape[:2]
        gray = cv2.cvtColor(frame_np, cv2.COLOR_RGB2GRAY)

        # ── SEARCH: find toilet + jorshik ──
        if state.toilet_step == "search":
            toilet = _find_template(gray, TOILET_TMPL, 0.5)
            if toilet is None:
                await asyncio.sleep(0.1)
                continue

            state.toilet_rect = toilet
            log.info("Toilet found: %s", toilet)

            jorshik = _find_template(gray, JORSHIK_TMPL, 0.5)
            if jorshik is None:
                await asyncio.sleep(0.1)
                continue

            jx, jy, jw, jh = jorshik
            jcx, jcy = jx + jw // 2, jy + jh // 2
            state.toilet_jorshik = (jcx, jcy)
            log.info("Jorshik at (%d, %d)", jcx, jcy)

            # Get client-area origin in screen coords
            hwnd = win32gui.FindWindow(None, GAME_WINDOW_TITLE)
            if hwnd:
                ctx.screen_ox, ctx.screen_oy = win32gui.ClientToScreen(hwnd, (0, 0))
            else:
                ctx.screen_ox, ctx.screen_oy = 0, 0
            log.info("Client origin on screen: (%d, %d)", ctx.screen_ox, ctx.screen_oy)

            path = _build_path(toilet, fh)
            if not path:
                log.warning("Empty path, re-searching")
                await asyncio.sleep(0.5)
                continue

            # Prepend smooth travel from jorshik to first sweep start
            first_sx, first_sy = path[0][0], path[0][1]
            travel = ((first_sx - jcx) ** 2 + (first_sy - jcy) ** 2) ** 0.5
            travel_dur = max(0.05, travel / 2000)  # ~2000 px/s
            path.insert(0, (jcx, jcy, first_sx, first_sy, travel_dur))

            ctx.path = path
            ctx.seg_idx = 0
            state.toilet_path = path
            log.info("Path: %d segments, screen %dx%d", len(path), fw, fh)

            # Grab jorshik — SendInput uses screen coords
            scx = jcx + ctx.screen_ox
            scy = jcy + ctx.screen_oy
            si_mouse_down(scx, scy)
            ctx.mouse_held = True
            ctx.last_x, ctx.last_y = scx, scy
            ctx.seg_start = time.monotonic()
            state.toilet_cursor = (jcx, jcy)
            state.toilet_step = "scrub"
            log.info("Scrubbing started (mouse held)")
            continue

        # ── SCRUB: zigzag drag — mouse stays held ──
        if state.toilet_step == "scrub":
            if ctx.seg_idx >= len(ctx.path):
                # Full clean done — NOW release
                log.info("Scrub complete — releasing mouse")
                _release(ctx)
                state.toilet_cursor = None
                state.toilet_step = "done"
                await asyncio.sleep(0.016)
                continue

            sx, sy, ex, ey, dur = ctx.path[ctx.seg_idx]
            elapsed = time.monotonic() - ctx.seg_start
            t = min(elapsed / dur, 1.0) if dur > 0 else 1.0

            cx = int(sx + (ex - sx) * t)
            cy = int(sy + (ey - sy) * t)
            # Convert client coords → screen coords for SendInput
            scx = cx + ctx.screen_ox
            scy = cy + ctx.screen_oy
            si_mouse_move(scx, scy)
            ctx.last_x, ctx.last_y = scx, scy
            state.toilet_cursor = (cx, cy)

            if t >= 1.0:
                ctx.seg_idx += 1
                ctx.seg_start = time.monotonic()

            await asyncio.sleep(0.016)
            continue

        # ── DONE: pause then re-search ──
        if state.toilet_step == "done":
            await asyncio.sleep(0.3)
            # Reset overlay data for next round
            state.toilet_rect = None
            state.toilet_jorshik = None
            state.toilet_path = None
            state.toilet_step = "search"
            continue

        await asyncio.sleep(0.05)
