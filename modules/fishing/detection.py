import os
import logging

import cv2
import numpy as np

from utils import resource_path

log = logging.getLogger(__name__)

_REF_DIR = resource_path("reference")
BOBBER_TMPL = cv2.imread(os.path.join(_REF_DIR, "bobber.png"), cv2.IMREAD_GRAYSCALE)
TAKE_TMPL = cv2.imread(os.path.join(_REF_DIR, "take.png"), cv2.IMREAD_GRAYSCALE)
GREEN_BAR_TMPL = cv2.imread(os.path.join(_REF_DIR, "green_bar.png"), cv2.IMREAD_GRAYSCALE)


def detect_panel(frame_np):
    """Detect fishing panel via full_throw_bar.png template match.

    Lower threshold (0.55) because the green zone shifts between frames.
    Searches bottom half of the screen only.

    Returns (squares, bar_rect) or (None, None).
    squares: list of (x, y, w, h) for each inventory square.
    bar_rect: (x, y, w, h) of the slider bar.
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
    if mv < 0.55:
        return None, None

    bar_x = ml[0]
    bar_y = ml[1] + y_off
    bar_rect = (bar_x, bar_y, tmpl_w, tmpl_h)

    # ── Find squares below bar ──
    # Use horizontal edge detection (Sobel) to find top border of squares
    sq_search = gray[bar_y + tmpl_h + 10:min(fh, bar_y + tmpl_h + 120),
                     bar_x:bar_x + tmpl_w]
    if sq_search.size == 0:
        log.info("Bar found at %s (score=%.2f), no squares", bar_rect, mv)
        return [], bar_rect

    edges_h = np.abs(cv2.Sobel(sq_search, cv2.CV_64F, 0, 1, ksize=3))
    row_profile = np.mean(edges_h, axis=1)
    mean_e = float(np.mean(row_profile))
    std_e = float(np.std(row_profile))
    sq_top = None
    for i in range(len(row_profile)):
        if row_profile[i] > mean_e + 2 * std_e:
            sq_top = bar_y + tmpl_h + 10 + i
            break
    if sq_top is None:
        log.info("Bar found at %s (score=%.2f), no squares", bar_rect, mv)
        return [], bar_rect

    # find square bottom (brightness jump back up)
    sq_h = 80
    for y in range(sq_top + 40, min(fh, sq_top + 200)):
        avg = float(np.mean(gray[y, bar_x:bar_x + tmpl_w]))
        if avg > 100:
            sq_h = y - sq_top
            break

    # generate evenly-spaced squares
    n_squares = max(1, round(tmpl_w / sq_h))
    if n_squares < 3:
        return None, None
    step = tmpl_w / n_squares
    squares = []
    for i in range(n_squares):
        x = int(bar_x + i * step)
        w = int(bar_x + (i + 1) * step) - x
        squares.append((x, sq_top, w, sq_h))

    log.info("Panel found: %d squares, bar=%s (score=%.2f)", len(squares), bar_rect, mv)
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
    mask = cv2.inRange(hsv, (35, 50, 85), (85, 255, 255))
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


def track_slider_bounds(frame_np, bar):
    """Track white slider with bounds. Returns (center, left, right) or None."""
    bx, by, bw, bh = bar
    crop = frame_np[by:by + bh, bx:bx + bw]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, (0, 0, 200), (180, 50, 255))
    cols = np.where(mask > 0)
    if len(cols[1]) == 0:
        return None
    left = bx + int(cols[1].min())
    right = bx + int(cols[1].max())
    center = bx + int(np.mean(cols[1]))
    return center, left, right
