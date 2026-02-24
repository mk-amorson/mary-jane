import asyncio
import logging
import time

import numpy as np

from core import get_game_rect
from .regions import SquareBounds, icon_region, bobber_region, take_region
from .detection import (
    detect_panel, tmpl_match, find_bobber_square,
    detect_bubbles, track_green, track_slider,
    SPACE_TMPL, BOBBER_TMPL, AD_TMPL, TAKE_TMPL,
)
from .trackers import SliderTracker, CameraTracker
from .input import tap_key, key_down, key_up, click_at, SC_SPACE, SC_A, SC_D

log = logging.getLogger(__name__)


# Fields to clear when entering each step.
# None for tuples/rects, False for booleans.
_CLEAR_ON_ENTER = {
    "init":   ["green_zone", "slider_x", "space_icon",
               "bobber_rect", "bubbles", "ad_icon", "camera_dir", "take_icon"],
    "cast":   ["bobber_rect", "bubbles", "ad_icon", "camera_dir", "take_icon"],
    "strike": ["green_zone", "slider_x", "space_icon", "take_icon"],
    "reel":   ["bobber_rect", "bubbles", "take_icon"],
    "take":   ["ad_icon", "camera_dir", "green_zone", "slider_x"],
}


class FishingContext:
    def __init__(self):
        self.slider = SliderTracker()
        self.camera = CameraTracker()
        self.beeped = False
        self.prev_in_green = False
        self.frame_cnt = 0
        self.baseline_circles: int | None = None
        self.bounds: SquareBounds | None = None
        self.take_cooldown: float = 0.0  # time.monotonic() until which take check is skipped
        self.held_key: int | None = None      # scan code of currently held key (reel)
        self.strike_pressed: bool = False     # prevent double-press on bubbles
        self.take_clicked: bool = False       # prevent repeated clicks on take


def _enter_step(state, ctx: FishingContext, step: str):
    """Transition to a new fishing step, clearing relevant state fields."""
    # release any held key from reel before switching steps
    if ctx.held_key is not None:
        key_up(ctx.held_key)
        ctx.held_key = None

    for field in _CLEAR_ON_ENTER.get(step, []):
        val = False if field == "bubbles" else None
        setattr(state, f"fishing_{field}", val)

    if step == "cast":
        ctx.slider.reset()
        ctx.beeped = False
        ctx.prev_in_green = False
    elif step == "strike":
        ctx.strike_pressed = False
    elif step == "reel":
        ctx.camera.reset()
    elif step == "take":
        ctx.take_clicked = False

    state.fishing_step = step
    log.info("→ %s", step.upper())


def _reset(state, ctx: FishingContext):
    """Full reset to idle."""
    if ctx.held_key is not None:
        key_up(ctx.held_key)
        ctx.held_key = None
    ctx.baseline_circles = None
    ctx.bounds = None
    ctx.slider.reset()
    ctx.camera.reset()
    ctx.beeped = False
    ctx.prev_in_green = False
    ctx.frame_cnt = 0

    state.fishing_step = "idle"
    state.fishing_squares = None
    state.fishing_bounds = None
    state.fishing_bar_rect = None
    state.fishing_green_zone = None
    state.fishing_slider_x = None
    state.fishing_space_icon = None
    state.fishing_bobber_rect = None
    state.fishing_bubbles = False
    state.fishing_ad_icon = None
    state.fishing_camera_dir = None
    state.fishing_take_icon = None
    state.fishing_take_pause = 0.0


def _ensure_bounds(state, ctx: FishingContext):
    """Compute SquareBounds from locked squares if not cached."""
    if ctx.bounds is None and state.fishing_squares:
        ctx.bounds = SquareBounds.from_squares(state.fishing_squares)
        state.fishing_bounds = ctx.bounds


def _check_take(frame_np, state, ctx: FishingContext) -> bool:
    """Check for take dialog in center of screen. Returns True if found."""
    if time.monotonic() < ctx.take_cooldown:
        return False
    fh, fw = frame_np.shape[:2]
    rgn = take_region(fw, fh)
    take = tmpl_match(frame_np, TAKE_TMPL, rgn, 0.85)
    if take:
        state.fishing_take_icon = take
        _enter_step(state, ctx, "take")
        return True
    return False


# ── Step handlers ──

async def _step_init(state, ctx: FishingContext, frame_np):
    fh, fw = frame_np.shape[:2]

    # priority: check for take dialog
    if _check_take(frame_np, state, ctx):
        if state.fishing_squares is None:
            squares, bar = detect_panel(frame_np)
            if squares:
                state.fishing_squares = squares
                state.fishing_bar_rect = bar
                _ensure_bounds(state, ctx)
        return

    # find panel (squares + bar) once
    if state.fishing_squares is None:
        squares, bar = detect_panel(frame_np)
        if not squares:
            return
        state.fishing_squares = squares
        state.fishing_bar_rect = bar
        _ensure_bounds(state, ctx)
        log.info("Squares locked (%d), bar=%s", len(squares), bar)
    else:
        _ensure_bounds(state, ctx)

    # look for space icon below squares
    bounds = ctx.bounds
    rgn = icon_region(bounds, fh)
    space = tmpl_match(frame_np, SPACE_TMPL, rgn, 0.95)
    state.fishing_space_icon = space

    if space:
        _enter_step(state, ctx, "cast")


async def _step_cast(state, ctx: FishingContext, frame_np):
    t0 = time.monotonic()
    bounds = ctx.bounds
    fh, fw = frame_np.shape[:2]

    # bar already locked from detect_panel in init
    # track slider + green zone
    bar = state.fishing_bar_rect
    if bar:
        state.fishing_green_zone = track_green(frame_np, bar)
        state.fishing_slider_x = track_slider(frame_np, bar)

        sx = state.fishing_slider_x
        gz = state.fishing_green_zone
        if sx is not None and gz:
            ctx.slider.push(time.monotonic(), sx)
            gx_l = gz[0]
            gx_r = gz[0] + gz[2]
            comp_x = sx + ctx.slider.speed * 0.03
            in_green = gx_l <= comp_x <= gx_r

            if in_green and not ctx.beeped:
                ctx.beeped = True
                tap_key(SC_SPACE)
            if not in_green and ctx.prev_in_green:
                ctx.beeped = False
            ctx.prev_in_green = in_green

    # check for take / bobber every 10th frame
    ctx.frame_cnt += 1
    if ctx.frame_cnt % 10 == 0:
        if _check_take(frame_np, state, ctx):
            return

        # bobber → transition to strike
        rgn = bobber_region(bounds, fw, fh)
        icon = tmpl_match(frame_np, BOBBER_TMPL, rgn, 0.8)
        if icon:
            bob_sq, baseline = find_bobber_square(frame_np, icon, bounds.h)
            state.fishing_bobber_rect = bob_sq if bob_sq else icon
            ctx.baseline_circles = baseline
            _enter_step(state, ctx, "strike")
            return

    elapsed = time.monotonic() - t0
    await asyncio.sleep(max(0.005, 0.02 - elapsed))


async def _step_strike(state, ctx: FishingContext, frame_np):
    bob = state.fishing_bobber_rect
    if bob:
        state.fishing_bubbles = detect_bubbles(frame_np, bob, ctx.baseline_circles)

    if state.fishing_bubbles and not ctx.strike_pressed:
        ctx.strike_pressed = True
        tap_key(SC_SPACE)

    # check for A-D icon → transition to reel
    bounds = ctx.bounds
    if bounds:
        fh = frame_np.shape[0]
        rgn = icon_region(bounds, fh)
        ad = tmpl_match(frame_np, AD_TMPL, rgn, 0.85)
        if ad:
            state.fishing_ad_icon = ad
            _enter_step(state, ctx, "reel")


async def _step_reel(state, ctx: FishingContext, frame_np):
    direction = ctx.camera.update(frame_np)
    if direction:
        state.fishing_camera_dir = direction

    # hold A/D based on camera direction
    d = state.fishing_camera_dir
    if d == "right":
        wanted = SC_A
    elif d == "left":
        wanted = SC_D
    else:
        wanted = None

    if wanted != ctx.held_key:
        if ctx.held_key is not None:
            key_up(ctx.held_key)
        if wanted is not None:
            key_down(wanted)
        ctx.held_key = wanted

    # check for take icon or space icon (skip take → straight to cast)
    if _check_take(frame_np, state, ctx):
        return

    bounds = ctx.bounds
    if bounds:
        fh = frame_np.shape[0]
        rgn = icon_region(bounds, fh)
        space = tmpl_match(frame_np, SPACE_TMPL, rgn, 0.95)
        if space:
            state.fishing_space_icon = space
            _enter_step(state, ctx, "cast")


async def _step_take(state, ctx: FishingContext, frame_np):
    bounds = ctx.bounds
    if not bounds:
        return

    # pause after click — wait it out
    now = time.monotonic()
    if state.fishing_take_pause > now:
        return

    fh, fw = frame_np.shape[:2]

    # wait until take dialog disappears before looking for space
    take_rgn = take_region(fw, fh)
    take_still = tmpl_match(frame_np, TAKE_TMPL, take_rgn, 0.75)
    if take_still:
        state.fishing_take_icon = take_still
        # click on first detection, then start 3s pause
        if not ctx.take_clicked:
            gr = state.game_rect
            if gr:
                tx, ty, tw, th = take_still
                sx = gr[0] + tx + tw // 2
                sy = gr[1] + ty + th // 2
                click_at(sx, sy)
            ctx.take_clicked = True
            state.fishing_take_pause = time.monotonic() + 3.0
        return

    # take dialog gone → look for space icon to cycle back to cast
    state.fishing_take_icon = None
    rgn = icon_region(bounds, fh)
    space = tmpl_match(frame_np, SPACE_TMPL, rgn, 0.95)
    if space:
        state.fishing_space_icon = space
        ctx.take_cooldown = time.monotonic() + 5.0
        _enter_step(state, ctx, "cast")


# ── Main loop ──

_STEP_SLEEP = {
    "init": 0.1,
    "cast": 0,      # handled inside _step_cast
    "strike": 0.1,
    "reel": 0.05,
    "take": 0.1,
}

_STEP_FN = {
    "init": _step_init,
    "cast": _step_cast,
    "strike": _step_strike,
    "reel": _step_reel,
    "take": _step_take,
}


async def fishing_bot_loop(state):
    log.info("Fishing bot loop started")
    ctx = FishingContext()

    while True:
        # inactive
        if not state.fishing_active:
            if state.fishing_step != "idle":
                _reset(state, ctx)
            await asyncio.sleep(0.2)
            continue

        if not state.frame_provider.running:
            state.frame_provider.start()
            # wait for WGC to deliver first frame
            for _ in range(20):
                await asyncio.sleep(0.1)
                if state.frame_provider.get_image() is not None:
                    break
        state.game_rect = get_game_rect()

        # first activation
        if state.fishing_step == "idle":
            state.fishing_step = "init"

        step = state.fishing_step
        fn = _STEP_FN.get(step)
        if fn is None:
            await asyncio.sleep(0.2)
            continue

        img = state.frame_provider.get_image()
        if img is None:
            await asyncio.sleep(0.2)
            continue

        frame_np = np.array(img)
        _ensure_bounds(state, ctx)

        try:
            await fn(state, ctx, frame_np)
        except Exception:
            log.exception("%s error", step.capitalize())

        # sleep (cast handles its own timing)
        sleep = _STEP_SLEEP.get(step, 0.2)
        if sleep > 0:
            await asyncio.sleep(sleep)
