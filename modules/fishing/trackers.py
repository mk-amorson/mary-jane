import numpy as np
from collections import deque


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
