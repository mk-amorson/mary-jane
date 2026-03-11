"""OverlayWindow — transparent click-through debug overlay over game window."""

import ctypes

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor, QPen

_GWL_EXSTYLE      = -20
_WS_EX_LAYERED    = 0x80000
_WS_EX_TRANSPARENT = 0x20
_WS_EX_TOOLWINDOW = 0x80
_CLICK_THROUGH    = _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW


class OverlayWindow(QWidget):
    def __init__(self, state):
        super().__init__()
        self._state = state
        self._snap = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.show()
        hwnd = int(self.winId())
        cur = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, cur | _CLICK_THROUGH)
        self.hide()

    def sync(self):
        s = self._state
        gr = s.game_rect

        show_fish2 = gr and (
            (s.fishing2_active and s.fishing2_step in ("cast", "strike", "reel", "end"))
            or (s.fishing2_debug and s.fishing2_bar_rect)
        )
        show_toilet = gr and s.toilet_active and s.toilet_step in ("search", "scrub", "done")

        if show_fish2 or show_toilet:
            gx, gy, gw, gh = gr
            geo = self.geometry()
            if geo.x() != gx or geo.y() != gy or geo.width() != gw or geo.height() != gh:
                self.setGeometry(gx, gy, gw, gh)
            if not self.isVisible():
                self.show()
            snap = (gr, s.fishing2_step, s.fishing2_debug,
                    s.fishing2_bar_rect,
                    s.fishing2_green_zone,
                    s.fishing2_slider_x, s.fishing2_pred_x,
                    s.fishing2_slider_bounds,
                    s.fishing2_bobber_rect,
                    s.fishing2_bubbles, s.fishing2_camera_dir,
                    s.fishing2_take_icon,
                    s.toilet_step, s.toilet_rect, s.toilet_jorshik,
                    s.toilet_cursor)
            if snap != self._snap:
                self._snap = snap
                self.update()
        elif self.isVisible():
            self.hide()
            self._snap = None

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        self._paint_fishing2(p)
        self._paint_toilet(p)
        p.end()

    def _paint_fishing2(self, p: QPainter):
        s = self._state
        step = s.fishing2_step

        if step == "cast" and s.fishing2_bar_rect:
            bx, by, bw, bh = s.fishing2_bar_rect
            p.setPen(QPen(QColor(255, 220, 50), 1))
            p.setBrush(QColor(255, 220, 50, 20))
            p.drawRect(bx, by - 2, bw, bh + 4)

        if step not in ("cast", "strike", "reel", "end"):
            return

        if step == "cast":
            bar = s.fishing2_bar_rect
            gz = s.fishing2_green_zone

            if gz:
                gx, gy, gw, gh = gz
                p.setPen(QPen(QColor(80, 255, 80), 2))
                p.setBrush(QColor(80, 255, 80, 40))
                p.drawRect(gx, gy, gw, gh)

            ref_y = gz[1] if gz else (bar[1] if bar else None)
            ref_h = gz[3] if gz else (bar[3] if bar else None)

            sb = s.fishing2_slider_bounds
            if sb and ref_y is not None:
                sl, sr = sb
                p.setPen(QPen(QColor(255, 255, 255, 180), 1))
                p.setBrush(QColor(255, 255, 255, 30))
                p.drawRect(sl, ref_y - 4, sr - sl, ref_h + 8)

            px = s.fishing2_pred_x
            if px is not None and ref_y is not None:
                p.setPen(QPen(QColor(255, 60, 60), 3))
                p.drawLine(px, ref_y - 10, px, ref_y + ref_h + 10)

        elif step == "strike":
            bob = s.fishing2_bobber_rect
            if bob:
                bx, by, bw, bh = bob
                if s.fishing2_bubbles:
                    p.setPen(QPen(QColor(255, 165, 0), 3))
                    p.setBrush(QColor(255, 165, 0, 30))
                else:
                    p.setPen(QPen(QColor(255, 80, 255), 2))
                    p.setBrush(QColor(255, 80, 255, 20))
                p.drawRect(bx, by, bw, bh)

        elif step == "end":
            tk = s.fishing2_take_icon
            if tk:
                tx, ty, tw, th = tk
                p.setPen(QPen(QColor(255, 220, 50), 2))
                p.setBrush(QColor(255, 220, 50, 30))
                p.drawRect(tx, ty, tw, th)

    def _paint_toilet(self, p: QPainter):
        s = self._state
        if not s.toilet_active or s.toilet_step == "idle":
            return

        # Toilet boundary — cyan rect
        tr = s.toilet_rect
        if tr:
            tx, ty, tw, th = tr
            p.setPen(QPen(QColor(0, 220, 255), 2))
            p.setBrush(QColor(0, 220, 255, 15))
            p.drawRect(tx, ty, tw, th)

            # Inner cleaning area — dashed
            mx = int(tw * 0.18)
            mt = int(th * 0.18)
            mb = int(th * 0.12)
            pen = QPen(QColor(0, 220, 255, 100), 1, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(tx + mx, ty + mt, tw - 2 * mx, th - mt - mb)

        # Jorshik position — green cross
        j = s.toilet_jorshik
        if j:
            jx, jy = j
            p.setPen(QPen(QColor(80, 255, 80), 2))
            p.drawLine(jx - 12, jy, jx + 12, jy)
            p.drawLine(jx, jy - 12, jx, jy + 12)

        # Zigzag path — dim lines
        path = s.toilet_path
        if path:
            p.setPen(QPen(QColor(255, 255, 255, 40), 1))
            for sx, sy, ex, ey, _dur in path:
                p.drawLine(sx, sy, ex, ey)

        # Current cursor — bright orange dot
        cur = s.toilet_cursor
        if cur:
            cx, cy = cur
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 140, 0))
            p.drawEllipse(cx - 6, cy - 6, 12, 12)
            # Outer ring
            p.setPen(QPen(QColor(255, 140, 0, 120), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(cx - 10, cy - 10, 20, 20)
