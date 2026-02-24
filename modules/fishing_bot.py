import os
import asyncio
import logging
import time
import winsound
from collections import deque

import cv2
import numpy as np

from core import get_game_rect
from utils import resource_path

log = logging.getLogger(__name__)

_REF_DIR = resource_path("reference")
_SPACE_TMPL = cv2.imread(os.path.join(_REF_DIR, "space.bmp"), cv2.IMREAD_GRAYSCALE)
_BOBBER_TMPL = cv2.imread(os.path.join(_REF_DIR, "bobber.png"), cv2.IMREAD_GRAYSCALE)
_AD_TMPL = cv2.imread(os.path.join(_REF_DIR, "a-d.png"), cv2.IMREAD_GRAYSCALE)
_TAKE_TMPL = cv2.imread(os.path.join(_REF_DIR, "take.png"), cv2.IMREAD_GRAYSCALE)


class SliderTracker:
    def __init__(self, maxlen=8):
        self._buf: deque[tuple[float, float]] = deque(maxlen=maxlen)

    def reset(self):
        self._buf.clear()

    def push(self, t: float, x: float):
        self._buf.append((t, x))

    @property
    def speed(self) -> float:
        if len(self._buf) < 3:
            return 0.0
        ts = np.array([p[0] for p in self._buf])
        xs = np.array([p[1] for p in self._buf])
        ts = ts - ts[0]
        n = len(ts)
        sx, sy = ts.sum(), xs.sum()
        sxy, sxx = (ts * xs).sum(), (ts * ts).sum()
        d = n * sxx - sx * sx
        return float((n * sxy - sx * sy) / d) if abs(d) > 1e-9 else 0.0


class CameraTracker:
    """Detect camera pan direction via optical flow on edge strips."""

    def __init__(self, maxlen=5):
        self._buf: deque[float] = deque(maxlen=maxlen)
        self._prev = None
        self._last_dir = None

    def reset(self):
        self._buf.clear()
        self._prev = None
        self._last_dir = None

    def update(self, frame_np) -> str | None:
        """Returns 'left', 'right', or None."""
        gray = cv2.cvtColor(frame_np, cv2.COLOR_RGB2GRAY)
        small = cv2.resize(gray, (0, 0), fx=0.25, fy=0.25)

        if self._prev is None:
            self._prev = small
            return None

        h, w = small.shape
        sw = w // 4  # 25% strips each side

        dxs = []
        for x1, x2 in [(0, sw), (w - sw, w)]:
            flow = cv2.calcOpticalFlowFarneback(
                self._prev[:, x1:x2], small[:, x1:x2], None,
                0.5, 2, 11, 2, 5, 1.1, 0,
            )
            dx = float(np.median(flow[..., 0]))
            dxs.append(dx)

        self._prev = small

        dx_avg = float(np.mean(dxs))
        self._buf.append(dx_avg)

        if len(self._buf) < 2:
            return None

        avg = float(np.mean(self._buf))
        # positive flow = scene moves right = camera pans left
        if avg > 0.15:
            d = "left"
        elif avg < -0.15:
            d = "right"
        else:
            d = self._last_dir  # keep previous during brief transitions

        if d and d != self._last_dir:
            log.info("Camera direction: %s (avg=%.2f)", d, avg)
            self._last_dir = d
        return d


# ── One-time detection ──

def _detect_squares(frame_np):
    h, w = frame_np.shape[:2]
    y_off = int(h * 0.7)
    crop = frame_np[y_off:, :]
    ch, cw = crop.shape[:2]

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_s, max_s = max(30, min(ch, cw) // 15), min(ch, cw) // 3
    cands = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < min_s or bh < min_s or bw > max_s or bh > max_s:
            continue
        if 0.7 <= bw / bh <= 1.4:
            cands.append((x, y, bw, bh, y + bh // 2))

    if len(cands) < 5:
        return None

    cands.sort(key=lambda s: s[4])
    best = []
    for i in range(len(cands)):
        cy, rh = cands[i][4], cands[i][3]
        grp = [s for s in cands if abs(s[4] - cy) < rh * 0.7]
        if 5 <= len(grp) <= 8 and len(grp) > len(best):
            best = grp

    if len(best) < 5:
        return None
    best.sort(key=lambda s: s[0])
    return [(x, y + y_off, bw, bh) for x, y, bw, bh, _ in best]


def _detect_bar(frame_np, squares):
    """Find slider bar once via green zone HSV. Returns (x,y,w,h) or None."""
    sq_top = min(s[1] for s in squares)
    sq_h = max(s[3] for s in squares)
    sq_left = min(s[0] for s in squares)
    sq_right = max(s[0] + s[2] for s in squares)

    y1 = max(0, sq_top - sq_h * 2)
    y2 = sq_top
    crop = frame_np[y1:y2, sq_left:sq_right]
    if crop.size == 0:
        return None

    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, (35, 50, 50), (85, 255, 255))
    gp = np.where(mask > 0)
    if len(gp[0]) == 0:
        return None

    gy_min, gy_max = int(gp[0].min()), int(gp[0].max())
    pad = max(2, (gy_max - gy_min) // 3)
    return (sq_left, y1 + gy_min - pad, sq_right - sq_left, (gy_max - gy_min) + pad * 2)


def _tmpl_match(frame_np, tmpl, region, threshold):
    """Template match in (x1,y1,x2,y2) region. Returns (x,y,w,h) or None."""
    if tmpl is None:
        return None
    x1, y1, x2, y2 = region
    fh, fw = frame_np.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(fw, x2), min(fh, y2)
    th, tw = tmpl.shape[:2]
    if y2 - y1 < th or x2 - x1 < tw:
        return None
    gray = cv2.cvtColor(frame_np[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
    res = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res)
    if mv >= threshold:
        return (x1 + ml[0], y1 + ml[1], tw, th)
    return None


# ── Per-frame tracking ──

def _track_green(frame_np, bar):
    bx, by, bw, bh = bar
    crop = frame_np[by:by + bh, bx:bx + bw]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, (35, 50, 50), (85, 255, 255))
    gp = np.where(mask > 0)
    if len(gp[0]) == 0:
        return None
    return (bx + int(gp[1].min()), by + int(gp[0].min()),
            int(gp[1].max()) - int(gp[1].min()),
            int(gp[0].max()) - int(gp[0].min()))


def _track_slider(frame_np, bar):
    bx, by, bw, bh = bar
    crop = frame_np[by:by + bh, bx:bx + bw]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, (0, 0, 200), (180, 50, 255))
    cols = np.where(mask > 0)
    if len(cols[1]) == 0:
        return None
    return bx + int(np.mean(cols[1]))


# ── Bobber ──

# baseline circle count without bubbles (calibrated on first frame)
_baseline_circles = None


def _find_bobber_square(frame_np, icon_rect):
    """From template match, find the actual gray square boundary."""
    global _baseline_circles

    ix, iy, iw, ih = icon_rect
    cx, cy = ix + iw // 2, iy + ih // 2
    r = int(max(iw, ih) * 0.85)
    fh, fw = frame_np.shape[:2]
    x1, y1 = max(0, cx - r), max(0, cy - r)
    x2, y2 = min(fw, cx + r), min(fh, cy + r)

    gray = cv2.cvtColor(frame_np[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    lcx, lcy = cx - x1, cy - y1
    best, best_a = None, 0
    for cnt in contours:
        bx, by, bw, bh = cv2.boundingRect(cnt)
        if bx <= lcx <= bx + bw and by <= lcy <= by + bh:
            a = bw * bh
            if a > best_a:
                best_a = a
                best = (x1 + bx, y1 + by, bw, bh)

    # calibrate baseline circle count
    if best:
        sq_gray = gray[best[1]-y1:best[1]-y1+best[3], best[0]-x1:best[0]-x1+best[2]]
        circles = cv2.HoughCircles(sq_gray, cv2.HOUGH_GRADIENT, 1.2, 15,
                                   param1=80, param2=20, minRadius=4, maxRadius=20)
        _baseline_circles = len(circles[0]) if circles is not None else 0
        log.info("Bobber baseline circles: %d", _baseline_circles)

    return best


def _detect_bubbles(frame_np, bobber_rect):
    """Detect bubbles as extra circles appearing in bobber square."""
    bx, by, bw, bh = bobber_rect
    fh, fw = frame_np.shape[:2]
    bx2 = min(fw, bx + bw)
    by2 = min(fh, by + bh)
    crop = frame_np[max(0, by):by2, max(0, bx):bx2]
    if crop.size == 0:
        return False

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1.2, 15,
                               param1=80, param2=20, minRadius=4, maxRadius=20)
    n = len(circles[0]) if circles is not None else 0

    baseline = _baseline_circles if _baseline_circles is not None else 3
    # bubbles = significantly more circles than baseline
    return n > baseline + 2


# ── Main loop ──

async def fishing_bot_loop(state):
    log.info("Fishing bot loop started")
    tracker = SliderTracker()
    camera_tracker = CameraTracker()
    beeped = False
    prev_in_green = False
    frame_cnt = 0

    def _reset():
        global _baseline_circles
        nonlocal beeped, prev_in_green, frame_cnt
        _baseline_circles = None
        state.fishing_step = "idle"
        state.fishing_squares = None
        state.fishing_bar_rect = None
        state.fishing_green_zone = None
        state.fishing_slider_x = None
        state.fishing_space_icon = None
        state.fishing_bobber_rect = None
        state.fishing_bubbles = False
        state.fishing_ad_icon = None
        state.fishing_camera_dir = None
        state.fishing_take_icon = None
        tracker.reset()
        camera_tracker.reset()
        beeped = False
        prev_in_green = False
        frame_cnt = 0

    while True:
        # ── Inactive ──
        if not state.fishing_active:
            if state.fishing_step != "idle":
                _reset()
            await asyncio.sleep(0.2)
            continue

        if not state.frame_provider.running:
            state.frame_provider.start()
        state.game_rect = get_game_rect()

        # first activation
        if state.fishing_step == "idle":
            state.fishing_step = "init"

        # ── INIT: find squares + wait for space icon ──
        if state.fishing_step == "init":
            img = state.frame_provider.get_image()
            if img is None:
                await asyncio.sleep(0.5)
                continue

            frame_np = np.array(img)

            try:
                # priority: check for take dialog (center of screen)
                fh, fw = frame_np.shape[:2]
                take_rgn = (fw // 5, fh // 4, fw * 4 // 5, fh * 3 // 4)
                take = _tmpl_match(frame_np, _TAKE_TMPL, take_rgn, 0.85)
                if take:
                    state.fishing_take_icon = take
                    if state.fishing_squares is None:
                        state.fishing_squares = _detect_squares(frame_np)
                    state.fishing_step = "take"
                    log.info("Take found → TAKE")
                    continue

                # find squares once
                if state.fishing_squares is None:
                    squares = _detect_squares(frame_np)
                    if not squares:
                        await asyncio.sleep(0.5)
                        continue
                    state.fishing_squares = squares
                    log.info("Squares locked (%d)", len(squares))

                # look for space icon → confirms step 1
                sq = state.fishing_squares
                sq_left = min(s[0] for s in sq)
                sq_right = max(s[0] + s[2] for s in sq)
                sq_bot = max(s[1] + s[3] for s in sq)
                fh = frame_np.shape[0]
                space_rgn = (sq_left, sq_bot, sq_right, fh)
                space = _tmpl_match(frame_np, _SPACE_TMPL, space_rgn, 0.95)
                state.fishing_space_icon = space

                if space:
                    state.fishing_step = "cast"
                    log.info("Space found → CAST")
                    continue
            except Exception:
                log.exception("Init error")

            await asyncio.sleep(0.5)
            continue

        # ── CAST (Заброс): lock bar, track slider, look for bobber ──
        if state.fishing_step == "cast":
            img = state.frame_provider.get_image()
            if img is None:
                await asyncio.sleep(0.02)
                continue

            t0 = time.monotonic()
            frame_np = np.array(img)
            sq = state.fishing_squares

            try:
                # lock bar on first detection
                if state.fishing_bar_rect is None:
                    bar = _detect_bar(frame_np, sq)
                    if bar:
                        state.fishing_bar_rect = bar
                        log.info("Slider bar locked: %s", bar)

                bar = state.fishing_bar_rect
                if bar:
                    state.fishing_green_zone = _track_green(frame_np, bar)
                    state.fishing_slider_x = _track_slider(frame_np, bar)

                    sx = state.fishing_slider_x
                    gz = state.fishing_green_zone
                    if sx is not None and gz:
                        tracker.push(time.monotonic(), sx)
                        gx_l = gz[0]
                        gx_r = gz[0] + gz[2]
                        comp_x = sx + tracker.speed * 0.03
                        in_green = gx_l <= comp_x <= gx_r

                        if in_green and not beeped:
                            beeped = True
                            winsound.Beep(800, 80)
                        if not in_green and prev_in_green:
                            beeped = False
                        prev_in_green = in_green

                # check for take / bobber every 10th frame
                frame_cnt += 1
                if frame_cnt % 10 == 0:
                    # priority: take dialog
                    fh, fw = frame_np.shape[:2]
                    take_rgn = (fw // 5, fh // 4, fw * 4 // 5, fh * 3 // 4)
                    take = _tmpl_match(frame_np, _TAKE_TMPL, take_rgn, 0.85)
                    if take:
                        state.fishing_take_icon = take
                        state.fishing_bar_rect = None
                        state.fishing_green_zone = None
                        state.fishing_slider_x = None
                        state.fishing_space_icon = None
                        tracker.reset()
                        beeped = False
                        prev_in_green = False
                        state.fishing_step = "take"
                        log.info("Take found → TAKE")
                        continue

                    # bobber → transition to strike
                    sq_right = max(s[0] + s[2] for s in sq)
                    sq_top = min(s[1] for s in sq)
                    sq_bot = max(s[1] + s[3] for s in sq)
                    sq_h = sq_bot - sq_top
                    fh, fw = frame_np.shape[:2]
                    region = (sq_right, max(0, sq_top - sq_h * 2),
                              min(fw, sq_right + sq_h * 6), min(fh, sq_bot + sq_h * 2))
                    icon = _tmpl_match(frame_np, _BOBBER_TMPL, region, 0.8)
                    if icon:
                        bob_sq = _find_bobber_square(frame_np, icon)
                        state.fishing_bobber_rect = bob_sq if bob_sq else icon
                        state.fishing_bar_rect = None
                        state.fishing_green_zone = None
                        state.fishing_slider_x = None
                        state.fishing_space_icon = None
                        tracker.reset()
                        beeped = False
                        prev_in_green = False
                        state.fishing_step = "strike"
                        log.info("Bobber found → STRIKE")
                        continue

            except Exception:
                log.exception("Cast tracking error")

            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0.005, 0.02 - elapsed))
            continue

        # ── STRIKE (Подсечка): watch bobber for bubbles, look for A-D ──
        if state.fishing_step == "strike":
            img = state.frame_provider.get_image()
            if img is None:
                await asyncio.sleep(0.1)
                continue

            try:
                frame_np = np.array(img)
                bob = state.fishing_bobber_rect
                if bob:
                    state.fishing_bubbles = _detect_bubbles(frame_np, bob)

                # check for A-D icon → transition to reel
                sq = state.fishing_squares
                if sq:
                    sq_left = min(s[0] for s in sq)
                    sq_right = max(s[0] + s[2] for s in sq)
                    sq_bot = max(s[1] + s[3] for s in sq)
                    fh = frame_np.shape[0]
                    ad_rgn = (sq_left, sq_bot, sq_right, fh)
                    ad = _tmpl_match(frame_np, _AD_TMPL, ad_rgn, 0.85)
                    if ad:
                        state.fishing_ad_icon = ad
                        state.fishing_bobber_rect = None
                        state.fishing_bubbles = False
                        camera_tracker.reset()
                        state.fishing_step = "reel"
                        log.info("A-D found → REEL")
                        continue
            except Exception:
                log.exception("Strike detection error")

            await asyncio.sleep(0.1)
            continue

        # ── REEL (Вытягивание): detect camera direction, watch for take ──
        if state.fishing_step == "reel":
            img = state.frame_provider.get_image()
            if img is None:
                await asyncio.sleep(0.05)
                continue

            try:
                frame_np = np.array(img)
                direction = camera_tracker.update(frame_np)
                if direction:
                    state.fishing_camera_dir = direction

                # check for take icon → transition to take (dialog in center of screen)
                fh, fw = frame_np.shape[:2]
                take_rgn = (fw // 5, fh // 4, fw * 4 // 5, fh * 3 // 4)
                take = _tmpl_match(frame_np, _TAKE_TMPL, take_rgn, 0.85)
                if take:
                    state.fishing_take_icon = take
                    state.fishing_ad_icon = None
                    state.fishing_camera_dir = None
                    camera_tracker.reset()
                    state.fishing_step = "take"
                    log.info("Take found → TAKE")
                    continue
            except Exception:
                log.exception("Reel tracking error")

            await asyncio.sleep(0.05)
            continue

        # ── TAKE (Забрать): highlight take icon, watch for space ──
        if state.fishing_step == "take":
            img = state.frame_provider.get_image()
            if img is None:
                await asyncio.sleep(0.1)
                continue

            try:
                frame_np = np.array(img)
                sq = state.fishing_squares
                if sq:
                    sq_left = min(s[0] for s in sq)
                    sq_right = max(s[0] + s[2] for s in sq)
                    sq_bot = max(s[1] + s[3] for s in sq)
                    fh = frame_np.shape[0]
                    icon_rgn = (sq_left, sq_bot, sq_right, fh)

                    # check for space → cycle back to cast
                    space = _tmpl_match(frame_np, _SPACE_TMPL, icon_rgn, 0.95)
                    if space:
                        state.fishing_space_icon = space
                        state.fishing_take_icon = None
                        state.fishing_bar_rect = None
                        state.fishing_green_zone = None
                        state.fishing_slider_x = None
                        tracker.reset()
                        beeped = False
                        prev_in_green = False
                        state.fishing_step = "cast"
                        log.info("Space found again → CAST")
                        continue
            except Exception:
                log.exception("Take detection error")

            await asyncio.sleep(0.1)
            continue

        await asyncio.sleep(0.2)
