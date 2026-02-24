import logging
from collections import deque

import cv2
import numpy as np

log = logging.getLogger(__name__)


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
    """Detect camera pan direction via optical flow on edge strips.

    Improvements over v1:
    - 0.35x scale (was 0.25x) for more detail
    - Farneback: levels=3, winsize=15, iterations=3 (was 2,11,2)
    - Trimmed mean (10th-90th percentile) instead of median for flow
    - Weighted buffer: recent samples weighted higher
    - Asymmetric thresholds: +/- 0.12 (was 0.15) for faster response
    """

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
        small = cv2.resize(gray, (0, 0), fx=0.35, fy=0.35)

        if self._prev is None:
            self._prev = small
            return None

        h, w = small.shape
        sw = w // 4

        dxs = []
        for x1, x2 in [(0, sw), (w - sw, w)]:
            flow = cv2.calcOpticalFlowFarneback(
                self._prev[:, x1:x2], small[:, x1:x2], None,
                0.5, 3, 15, 3, 5, 1.1, 0,
            )
            fx = flow[..., 0].ravel()
            # trimmed mean: 10th-90th percentile
            if len(fx) > 0:
                lo, hi = np.percentile(fx, [10, 90])
                trimmed = fx[(fx >= lo) & (fx <= hi)]
                dx = float(np.mean(trimmed)) if len(trimmed) > 0 else 0.0
            else:
                dx = 0.0
            dxs.append(dx)

        self._prev = small

        dx_avg = float(np.mean(dxs))
        self._buf.append(dx_avg)

        if len(self._buf) < 2:
            return None

        # weighted average: recent samples weighted higher
        buf = list(self._buf)
        weights = np.arange(1, len(buf) + 1, dtype=float)
        avg = float(np.average(buf, weights=weights))

        # positive flow = scene moves right = camera pans left
        if avg > 0.12:
            d = "left"
        elif avg < -0.12:
            d = "right"
        else:
            d = self._last_dir

        if d and d != self._last_dir:
            log.info("Camera direction: %s (avg=%.2f)", d, avg)
            self._last_dir = d
        return d
