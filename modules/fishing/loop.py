"""Fishing v2 — simplified state machine with green_bar.png detection.

4 steps: cast → strike → reel → end → cast
Memory (pymem) required for reel direction.
"""
import asyncio
import logging
import time

import cv2
import numpy as np

from core import get_game_rect
from .detection import (
    tmpl_match, detect_bubbles,
    track_green, track_slider, track_slider_bounds,
    GREEN_BAR_TMPL, BOBBER_TMPL, TAKE_TMPL,
)
from .trackers import SliderTracker
from .memory import GTA5Memory, HeadingTracker
from .input import tap_key, key_down, key_up, click_at, SC_SPACE, SC_A, SC_D
from .regions import take_region

log = logging.getLogger(__name__)

_SC_NAMES = {SC_SPACE: "SPACE", SC_A: "A", SC_D: "D"}
_t0 = 0.0


def _ts():
    return f"+{time.monotonic() - _t0:.3f}s"


def _log_key(action, sc):
    log.info("%s  KEY %s %s", _ts(), action, _SC_NAMES.get(sc, hex(sc)))


# ── Context ──

class _Ctx:
    def __init__(self):
        self.mem = GTA5Memory()
        self.heading = HeadingTracker(self.mem)
        self.slider = SliderTracker()
        self.held_key = None
        self.bar_rect = None
        self.green_match = None
        self.no_slider_frames = 0
        self.observed_left = None
        self.observed_right = None
        self.prev_slider_x = None
        self.slider_dir = 0        # +1 right, -1 left
        self.bounce_count = 0
        self.calibrated = False
        self.locked_green = None    # fixed green zone from first detection
        self.panel_found = False     # fishing panel detected (slider seen)
        self.baseline_circles = None
        self.strike_pressed = False
        self.take_clicked = False
        self.end_enter_time = 0.0


# ── Bar detection from green_bar match ──

def _save_bar_rect(rect):
    from auth.token_store import _CONFIG_PATH
    import json as _json
    data = {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        pass
    data["fishing_bar_rect"] = list(rect)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False)
    log.info("Bar rect saved: %s", rect)


def _load_bar_rect():
    from auth.token_store import _CONFIG_PATH
    import json as _json
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = _json.load(f)
        r = data.get("fishing_bar_rect")
        if r and len(r) == 4:
            return tuple(r)
    except (FileNotFoundError, _json.JSONDecodeError):
        pass
    return None


def _search_region(frame_np, green_match):
    """Wide search region around green_bar match for slider/zone tracking."""
    gx, gy, gw, gh = green_match
    fh, fw = frame_np.shape[:2]
    cx = gx + gw // 2
    x1 = max(0, cx - 700)
    x2 = min(fw, cx + 700)
    return (x1, gy, x2 - x1, gh)


# ── Step transitions ──

def _enter_step(state, ctx, step):
    prev = state.fishing2_step

    if ctx.held_key is not None:
        _log_key("UP", ctx.held_key)
        key_up(ctx.held_key)
        ctx.held_key = None

    if step == "cast":
        ctx.slider.reset()
        ctx.strike_pressed = False
        ctx.take_clicked = False
        ctx.bar_rect = None
        ctx.green_match = None
        ctx.locked_green = None
        ctx.panel_found = False
        state.fishing2_bar_rect = None
        state.fishing2_calibrated = False
        state.fishing2_green_zone = None
        state.fishing2_slider_x = None
        state.fishing2_bobber_rect = None
        state.fishing2_bubbles = False
        state.fishing2_camera_dir = None
        state.fishing2_take_icon = None
        state.fishing2_take_pause = 0.0
    elif step == "strike":
        ctx.strike_pressed = False
        ctx.heading.reset()
        state.fishing2_green_zone = None
        state.fishing2_slider_x = None
        state.fishing2_camera_dir = None
        state.fishing2_take_icon = None
    elif step == "reel":
        state.fishing2_bobber_rect = None
        state.fishing2_bubbles = False
        state.fishing2_take_icon = None
    elif step == "end":
        ctx.take_clicked = False
        ctx.end_enter_time = time.monotonic()
        state.fishing2_camera_dir = None

    state.fishing2_step = step
    log.info("%s  ── %s → %s ──", _ts(), prev.upper(), step.upper())


def _reset(state, ctx):
    if ctx.held_key is not None:
        key_up(ctx.held_key)
        ctx.held_key = None
    ctx.slider.reset()
    ctx.heading.reset()
    ctx.bar_rect = None
    ctx.green_match = None
    ctx.locked_green = None
    ctx.panel_found = False
    ctx.baseline_circles = None
    ctx.strike_pressed = False
    ctx.take_clicked = False

    state.fishing2_step = "idle"
    state.fishing2_bar_rect = None
    state.fishing2_calibrated = False
    state.fishing2_green_zone = None
    state.fishing2_slider_x = None
    state.fishing2_bobber_rect = None
    state.fishing2_bubbles = False
    state.fishing2_camera_dir = None
    state.fishing2_take_icon = None
    state.fishing2_take_pause = 0.0


# ── Step handlers ──

async def _step_cast(state, ctx, frame_np):
    """Track slider in bar_rect → lock green zone → SPACE when in green (75% rule)."""
    fh, fw = frame_np.shape[:2]

    # ── Debug / calibration mode: GREEN_BAR_TMPL search ──
    if state.fishing2_debug:
        await _step_cast_debug(state, ctx, frame_np)
        return

    # ── Normal mode: use saved bar_rect directly ──

    # Phase 0: load saved bar_rect
    if ctx.bar_rect is None:
        saved = _load_bar_rect()
        if saved is None:
            log.warning("%s  CAST: no saved bar_rect — run calibration first", _ts())
            return
        ctx.bar_rect = saved
        ctx.no_slider_frames = 0
        ctx.panel_found = False
        state.fishing2_bar_rect = saved
        log.info("%s  CAST: using saved bar_rect %s", _ts(), saved)

    bar = ctx.bar_rect

    # Phase 1: wait for fishing panel (slider appears)
    sx = track_slider(frame_np, bar)
    if not ctx.panel_found:
        if sx is None:
            return  # panel not visible yet
        ctx.panel_found = True
        ctx.no_slider_frames = 0
        log.info("%s  CAST: panel detected (slider at %d)", _ts(), sx)

    # Phase 2: lock green zone (only when slider not overlapping)
    state.fishing2_slider_x = sx
    state.fishing2_slider_bounds = None

    if ctx.locked_green is None:
        if sx is not None:
            gz = track_green(frame_np, bar)
            if gz is not None:
                # Check slider doesn't overlap green zone
                green_center = gz[0] + gz[2] / 2
                margin = 20
                if abs(sx - green_center) > gz[2] / 2 + margin:
                    ctx.locked_green = gz
                    log.info("%s  CAST: green zone locked: %s (slider at %d)", _ts(), gz, sx)
        gz = ctx.locked_green
    else:
        gz = ctx.locked_green

    state.fishing2_green_zone = gz

    # No slider for 50 frames → reset
    if sx is None:
        ctx.no_slider_frames += 1
        if ctx.no_slider_frames > 50:
            log.info("%s  CAST: no slider for 50 frames, resetting", _ts())
            ctx.bar_rect = None
            ctx.locked_green = None
            ctx.panel_found = False
            ctx.no_slider_frames = 0
            ctx.slider.reset()
        return
    ctx.no_slider_frames = 0

    # Phase 3: predict + SPACE
    if gz:
        ctx.slider.push(time.monotonic(), sx)
        spd = ctx.slider.speed
        comp_x = sx + spd * state.fishing2_pred_time
        bx, _, bw, _ = ctx.bar_rect
        comp_x = max(bx, min(bx + bw, comp_x))
        state.fishing2_pred_x = int(comp_x)

        gx_l = gz[0]
        gx_r = gz[0] + gz[2]
        in_green = gx_l <= comp_x <= gx_r
        if in_green:
            ok = True
            if spd > 0:
                limit = gx_l + (gx_r - gx_l) * 0.75
                if comp_x > limit:
                    ok = False
            elif spd < 0:
                limit = gx_r - (gx_r - gx_l) * 0.75
                if comp_x < limit:
                    ok = False
            if ok:
                log.info("%s  CAST: slider=%d green=[%d..%d] spd=%.0f → TAP SPACE",
                         _ts(), sx, gx_l, gx_r, spd)
                _log_key("TAP", SC_SPACE)
                tap_key(SC_SPACE)
                _enter_step(state, ctx, "strike")
    else:
        state.fishing2_pred_x = None


async def _step_cast_debug(state, ctx, frame_np):
    """Debug/calibration: GREEN_BAR_TMPL search + bounce counting."""
    fh, fw = frame_np.shape[:2]

    # Phase 1: find green_bar template
    if ctx.bar_rect is None:
        bottom_half = (0, fh // 2, fw, fh)
        match = tmpl_match(frame_np, GREEN_BAR_TMPL, bottom_half, 0.8)
        if match is None:
            return

        region = _search_region(frame_np, match)
        gz = track_green(frame_np, region)
        sx = track_slider(frame_np, region)
        if gz is None or sx is None:
            return

        ctx.green_match = match
        ctx.bar_rect = region
        ctx.no_slider_frames = 0
        state.fishing2_green_zone = gz

        ctx.observed_left = None
        ctx.observed_right = None
        ctx.prev_slider_x = None
        ctx.slider_dir = 0
        ctx.bounce_count = 0
        ctx.calibrated = False

        log.info("%s  CAST: green_bar at %s, search=%s", _ts(), match, region)
        return

    # Phase 2: track slider bounds + calibrate
    bar = ctx.bar_rect
    if ctx.locked_green is None:
        gz = track_green(frame_np, bar)
        if gz is not None:
            ctx.locked_green = gz
            log.info("%s  CAST: green zone locked: %s", _ts(), gz)
    else:
        gz = ctx.locked_green

    bounds = track_slider_bounds(frame_np, bar)
    if bounds:
        sx, sl, sr = bounds
        state.fishing2_slider_bounds = (sl, sr)

        if ctx.observed_left is None or sl < ctx.observed_left:
            ctx.observed_left = sl
        if ctx.observed_right is None or sr > ctx.observed_right:
            ctx.observed_right = sr

        if ctx.prev_slider_x is not None:
            dx = sx - ctx.prev_slider_x
            if abs(dx) > 2:
                new_dir = 1 if dx > 0 else -1
                if ctx.slider_dir != 0 and new_dir != ctx.slider_dir:
                    ctx.bounce_count += 1
                    log.info("%s  DEBUG: bounce #%d, bar=[%d..%d]",
                             _ts(), ctx.bounce_count, ctx.observed_left, ctx.observed_right)
                ctx.slider_dir = new_dir
        ctx.prev_slider_x = sx

        if ctx.observed_left is not None:
            _, by, _, bh = ctx.bar_rect
            refined = (ctx.observed_left, by, ctx.observed_right - ctx.observed_left, bh)
            state.fishing2_bar_rect = refined

            if ctx.bounce_count >= 5 and not ctx.calibrated:
                ctx.calibrated = True
                ctx.bar_rect = refined
                _save_bar_rect(refined)
                state.fishing2_calibrated = True
                log.info("%s  DEBUG: calibrated! bar=%s", _ts(), refined)
    else:
        sx = None
        state.fishing2_slider_bounds = None

    state.fishing2_green_zone = gz
    state.fishing2_slider_x = sx

    if sx is None:
        ctx.no_slider_frames += 1
        if ctx.no_slider_frames > 50:
            log.info("%s  CAST: no slider for 50 frames, resetting", _ts())
            ctx.bar_rect = None
            ctx.green_match = None
            ctx.no_slider_frames = 0
            ctx.slider.reset()
        return
    ctx.no_slider_frames = 0

    if gz:
        ctx.slider.push(time.monotonic(), sx)
        spd = ctx.slider.speed
        comp_x = sx + spd * state.fishing2_pred_time
        bx, _, bw, _ = ctx.bar_rect
        comp_x = max(bx, min(bx + bw, comp_x))
        state.fishing2_pred_x = int(comp_x)
        # debug mode: visualize only, no SPACE
    else:
        state.fishing2_pred_x = None


async def _step_strike(state, ctx, frame_np):
    """Find bobber → detect bubbles → TAP SPACE → heading.moving → reel."""
    fh, fw = frame_np.shape[:2]

    if not ctx.strike_pressed:
        # Phase 1: find bobber — search right half of bottom screen
        bob = state.fishing2_bobber_rect
        if bob is None:
            rgn = (fw // 4, fh // 3, fw, fh)
            icon = tmpl_match(frame_np, BOBBER_TMPL, rgn, 0.8)
            if icon:
                state.fishing2_bobber_rect = icon
                # count baseline circles inside bobber rect
                ix, iy, iw, ih = icon
                crop = cv2.cvtColor(frame_np[iy:iy+ih, ix:ix+iw], cv2.COLOR_RGB2GRAY)
                circles = cv2.HoughCircles(crop, cv2.HOUGH_GRADIENT, 1.2, 15,
                                           param1=80, param2=20, minRadius=4, maxRadius=20)
                ctx.baseline_circles = len(circles[0]) if circles is not None else 0
                log.info("%s  STRIKE: bobber at %s, baseline=%d", _ts(), icon, ctx.baseline_circles)
            return

        # Phase 2: detect bubbles in the same bobber rect
        bubbles = detect_bubbles(frame_np, bob, ctx.baseline_circles)
        state.fishing2_bubbles = bubbles

        if bubbles:
            ctx.strike_pressed = True
            log.info("%s  STRIKE: bubbles → TAP SPACE", _ts())
            _log_key("TAP", SC_SPACE)
            tap_key(SC_SPACE)
            state.fishing2_bobber_rect = None
            state.fishing2_bubbles = False
        return

    # Phase 3: after strike, detect reel start via heading
    if ctx.mem.connected:
        ctx.heading.update()
        if ctx.heading.moving:
            log.info("%s  Heading moving → REEL", _ts())
            _enter_step(state, ctx, "reel")


async def _step_reel(state, ctx, frame_np):
    """Hold A/D based on heading direction. Stabilize → END."""
    if not ctx.mem.connected:
        log.warning("%s  Memory disconnected in reel → END", _ts())
        _enter_step(state, ctx, "end")
        return

    direction = ctx.heading.update()
    if direction:
        state.fishing2_camera_dir = direction

    d = state.fishing2_camera_dir
    if d == "right":
        wanted = SC_A
    elif d == "left":
        wanted = SC_D
    else:
        wanted = None

    if wanted != ctx.held_key:
        if ctx.held_key is not None:
            _log_key("UP", ctx.held_key)
            key_up(ctx.held_key)
        if wanted is not None:
            _log_key("DOWN", wanted)
            key_down(wanted)
        ctx.held_key = wanted

    # Fast path: TAKE dialog visible → click immediately
    fh, fw = frame_np.shape[:2]
    rgn = take_region(fw, fh)
    take = tmpl_match(frame_np, TAKE_TMPL, rgn, 0.85)
    if take:
        state.fishing2_take_icon = take
        gr = state.game_rect
        if gr:
            tx, ty, tw, th = take
            sx = gr[0] + tx + tw // 2
            sy = gr[1] + ty + th // 2
            log.info("%s  REEL: TAKE visible → click (%d,%d)", _ts(), sx, sy)
            click_at(sx, sy)
        _enter_step(state, ctx, "end")
        ctx.take_clicked = True
        state.fishing2_take_pause = time.monotonic() + 3.0
        state.fishing2_take_icon = None
        return

    # Heading stabilized → go to END
    if not ctx.heading.moving:
        log.info("%s  Heading stable → END", _ts())
        _enter_step(state, ctx, "end")


async def _step_end(state, ctx, frame_np):
    """Timer after reel → find take → click → pause → CAST."""
    fh, fw = frame_np.shape[:2]
    now = time.monotonic()
    elapsed = now - ctx.end_enter_time

    # Pause after take click
    if state.fishing2_take_pause > now:
        return

    # Take was clicked and pause ended → back to cast
    if ctx.take_clicked:
        log.info("%s  END: take done → CAST", _ts())
        _enter_step(state, ctx, "cast")
        return

    # Phase 1: wait 2s for reel animation to finish (memory told us heading stopped)
    if elapsed < 2.0:
        return

    # Phase 2: look for take dialog
    rgn = take_region(fw, fh)
    take = tmpl_match(frame_np, TAKE_TMPL, rgn, 0.85)
    if take:
        state.fishing2_take_icon = take
        gr = state.game_rect
        if gr:
            tx, ty, tw, th = take
            sx = gr[0] + tx + tw // 2
            sy = gr[1] + ty + th // 2
            log.info("%s  END: clicking TAKE at (%d,%d)", _ts(), sx, sy)
            click_at(sx, sy)
        ctx.take_clicked = True
        state.fishing2_take_pause = time.monotonic() + 3.0
        state.fishing2_take_icon = None
        return

    # Phase 3: after 6s total without take → check if fishing bar active (fish escaped)
    if elapsed > 6.0:
        saved = _load_bar_rect()
        if saved and track_slider(frame_np, saved) is not None:
            log.info("%s  END: slider found in bar → fish escaped → CAST", _ts())
            _enter_step(state, ctx, "cast")
            return
        # Fallback: GREEN_BAR_TMPL search
        bottom_half = (0, fh // 2, fw, fh)
        gb = tmpl_match(frame_np, GREEN_BAR_TMPL, bottom_half, 0.8)
        if gb:
            log.info("%s  END: green_bar found → fish escaped → CAST", _ts())
            _enter_step(state, ctx, "cast")


# ── Main loop ──

_STEP_FN = {
    "cast": _step_cast,
    "strike": _step_strike,
    "reel": _step_reel,
    "end": _step_end,
}

_STEP_SLEEP = {
    "cast": 0.02,
    "strike": 0.1,
    "reel": 0.05,
    "end": 0.1,
}


async def fishing2_bot_loop(state):
    global _t0
    log.info("Fishing v2 loop started")
    ctx = _Ctx()

    while True:
        if not state.fishing2_active:
            if state.fishing2_step != "idle":
                log.info("%s  Fishing v2 deactivated → IDLE", _ts())
                _reset(state, ctx)
            await asyncio.sleep(0.2)
            continue

        # First activation
        if state.fishing2_step == "idle":
            _t0 = time.monotonic()
            saved = _load_bar_rect()
            if saved:
                state.fishing2_bar_rect = saved
                log.info("Loaded saved bar_rect: %s", saved)
            if not ctx.mem.connected:
                if ctx.mem.connect():
                    log.info("Memory reader connected (v2)")
                else:
                    log.warning("Memory reader unavailable — v2 requires memory for reel")

        if not state.frame_provider.running:
            state.frame_provider.start()
            for _ in range(20):
                await asyncio.sleep(0.1)
                if state.frame_provider.get_image() is not None:
                    break
        state.game_rect = get_game_rect()

        if state.fishing2_step == "idle":
            state.fishing2_step = "cast"

        step = state.fishing2_step
        fn = _STEP_FN.get(step)
        if fn is None:
            await asyncio.sleep(0.2)
            continue

        img = state.frame_provider.get_image()
        if img is None:
            await asyncio.sleep(0.2)
            continue

        frame_np = np.array(img)

        try:
            await fn(state, ctx, frame_np)
        except Exception:
            log.exception("%s error in v2 %s", _ts(), step)

        sleep = _STEP_SLEEP.get(step, 0.2)
        if sleep > 0:
            await asyncio.sleep(sleep)
