import os
import logging

import cv2
import numpy as np

from utils import resource_path

log = logging.getLogger(__name__)

_REF_DIR = resource_path("reference")
SPACE_TMPL = cv2.imread(os.path.join(_REF_DIR, "space.bmp"), cv2.IMREAD_GRAYSCALE)
BOBBER_TMPL = cv2.imread(os.path.join(_REF_DIR, "bobber.png"), cv2.IMREAD_GRAYSCALE)
AD_TMPL = cv2.imread(os.path.join(_REF_DIR, "a-d.png"), cv2.IMREAD_GRAYSCALE)
TAKE_TMPL = cv2.imread(os.path.join(_REF_DIR, "take.png"), cv2.IMREAD_GRAYSCALE)
BAR_TMPL = cv2.imread(os.path.join(_REF_DIR, "space_bar.png"), cv2.IMREAD_GRAYSCALE)


def detect_panel(frame_np):
    """Detect fishing panel: slider bar + squares below it.

    Uses space_bar.png template to anchor on the ruler bar, then finds
    squares below by scanning dark interiors in the horizontal profile.

    Returns (squares, bar_rect) or (None, None).
    squares: list of (x, y, w, h) for each inventory square.
    bar_rect: (x, y, w, h) of the ruler/slider bar.
    """
    if BAR_TMPL is None:
        return None, None

    fh, fw = frame_np.shape[:2]
    gray = cv2.cvtColor(frame_np, cv2.COLOR_RGB2GRAY)
    tmpl_h, tmpl_w = BAR_TMPL.shape

    # search bottom half only
    y_off = fh // 2
    crop = gray[y_off:, :]
    if crop.shape[0] < tmpl_h or crop.shape[1] < tmpl_w:
        return None, None

    res = cv2.matchTemplate(crop, BAR_TMPL, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res)
    if mv < 0.7:
        return None, None

    mx, my = ml[0], ml[1] + y_off

    # find bar horizontal extent via bright tick marks (> 100)
    bar_mid_y = my + tmpl_h // 2
    bar_row = gray[bar_mid_y, :]
    bright = bar_row > 100
    search_l = max(0, mx - 1000)
    search_r = min(fw, mx + tmpl_w + 1000)
    bp = np.where(bright[search_l:search_r])[0]
    if len(bp) == 0:
        return None, None
    bp = bp + search_l
    bar_x1, bar_x2 = int(bp[0]), int(bp[-1])
    bar_rect = (bar_x1, my, bar_x2 - bar_x1, tmpl_h)

    # find square top border: scan below bar, skip first 20 rows (gap),
    # find first row where mean brightness drops below 38 (dark interior)
    sq_top = None
    for y in range(my + tmpl_h + 20, min(fh, my + tmpl_h + 120)):
        avg = float(np.mean(gray[y, bar_x1:bar_x2]))
        if avg < 38:
            sq_top = y - 1  # border row is one above
            break
    if sq_top is None:
        return None, None

    # horizontal profile 10px into dark interior to find individual squares
    scan_y = min(sq_top + 10, fh - 1)
    mid_row = gray[scan_y, :]

    # dark pixels (< 40) in bar vicinity = square interiors
    is_dark = mid_row < 40
    mask = np.zeros_like(is_dark)
    mask[max(0, bar_x1 - 150):min(fw, bar_x2 + 150)] = True
    is_dark = is_dark & mask

    changes = np.diff(is_dark.astype(int))
    enters = np.where(changes == 1)[0] + 1
    exits = np.where(changes == -1)[0] + 1
    if len(is_dark) > 0 and is_dark[0]:
        enters = np.concatenate([[0], enters])
    if len(is_dark) > 0 and is_dark[-1]:
        exits = np.concatenate([exits, [len(is_dark)]])

    sq_interiors = []
    for s, e in zip(enters, exits):
        w = e - s
        if w > 50:
            sq_interiors.append((int(s), int(w)))

    if len(sq_interiors) < 5:
        return None, None

    # squares are roughly square: height ≈ median interior width + borders
    widths = [w for _, w in sq_interiors]
    sq_size = int(np.median(widths))
    sq_h = sq_size + 2  # +2 for border pixels

    squares = []
    for x, w in sq_interiors:
        # include border (1px each side)
        squares.append((x - 1, sq_top, w + 2, sq_h))

    # constrain bar width to match squares extent exactly
    sq_left = squares[0][0]
    sq_right = squares[-1][0] + squares[-1][2]
    bar_rect = (sq_left, my, sq_right - sq_left, tmpl_h)

    log.info("Panel found: %d squares, bar=%s", len(squares), bar_rect)
    return squares, bar_rect


def tmpl_match(frame_np, tmpl, region, threshold):
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


def find_bobber_square(frame_np, icon_rect, sq_size_hint: int = 0):
    """From template match, find the gray square boundary around the bobber.

    The bobber sits inside a small gray square (~80-120px), similar in size
    to the inventory squares. We search for the tightest square-ish contour
    around the template match center.

    Args:
        sq_size_hint: approximate expected square size (from inventory squares).
                      If 0, uses icon dimensions as guide.

    Returns (rect, baseline_circles) tuple.
    """
    ix, iy, iw, ih = icon_rect
    cx, cy = ix + iw // 2, iy + ih // 2

    # search radius: ~2x expected square size
    expected = sq_size_hint if sq_size_hint > 0 else max(iw, ih) * 2
    r = int(expected * 1.2)
    fh, fw = frame_np.shape[:2]
    x1, y1 = max(0, cx - r), max(0, cy - r)
    x2, y2 = min(fw, cx + r), min(fh, cy + r)

    gray = cv2.cvtColor(frame_np[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    lcx, lcy = cx - x1, cy - y1

    # size limits for the gray square
    min_side = max(40, expected // 3)
    max_side = expected * 2

    # find the SMALLEST contour that contains the center and is square-ish
    best, best_a = None, float("inf")
    for cnt in contours:
        bx, by, bw, bh = cv2.boundingRect(cnt)
        # must contain template center
        if not (bx <= lcx <= bx + bw and by <= lcy <= by + bh):
            continue
        # must be reasonable size
        if bw < min_side or bh < min_side or bw > max_side or bh > max_side:
            continue
        # must be roughly square (aspect 0.5 - 2.0)
        ratio = bw / bh if bh > 0 else 0
        if not (0.5 <= ratio <= 2.0):
            continue
        a = bw * bh
        if a < best_a:
            best_a = a
            best = (x1 + bx, y1 + by, bw, bh)

    baseline_circles = None
    if best:
        sq_gray = gray[best[1]-y1:best[1]-y1+best[3], best[0]-x1:best[0]-x1+best[2]]
        circles = cv2.HoughCircles(sq_gray, cv2.HOUGH_GRADIENT, 1.2, 15,
                                   param1=80, param2=20, minRadius=4, maxRadius=20)
        baseline_circles = len(circles[0]) if circles is not None else 0
        log.info("Bobber square: %s, baseline circles: %d", best, baseline_circles)

    return best, baseline_circles


def detect_bubbles(frame_np, bobber_rect, baseline_circles):
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

    baseline = baseline_circles if baseline_circles is not None else 3
    return n > baseline + 2


def track_green(frame_np, bar):
    """Track green zone position in slider bar. Returns (x,y,w,h) or None."""
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


def track_slider(frame_np, bar):
    """Track white slider position in bar. Returns x coordinate or None."""
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
