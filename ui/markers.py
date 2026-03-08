"""Marker overlays — 3D arrow compass and world-space circle."""

import math
import ctypes

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QPolygonF, QBrush

from ui.styles import pixel_font

_GWL_EXSTYLE      = -20
_WS_EX_LAYERED    = 0x80000
_WS_EX_TRANSPARENT = 0x20
_WS_EX_TOOLWINDOW = 0x80
_CLICK_THROUGH    = _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW


def w2s(target, cam_pos, cam_right, cam_fwd, cam_up, game_rect, fov=50.0):
    """Project world position to screen coords relative to game window."""
    dx = target[0] - cam_pos[0]
    dy = target[1] - cam_pos[1]
    dz = target[2] - cam_pos[2]

    depth = dx * cam_fwd[0] + dy * cam_fwd[1] + dz * cam_fwd[2]
    if depth < 0.1:
        return None

    horiz = dx * cam_right[0] + dy * cam_right[1] + dz * cam_right[2]
    vert = dx * cam_up[0] + dy * cam_up[1] + dz * cam_up[2]

    _, _, gw, gh = game_rect
    f = 1.0 / math.tan(math.radians(fov / 2))
    asp = gw / gh

    sx = gw / 2 + (horiz / depth) * f * gw / (2 * asp)
    sy = gh / 2 - (vert / depth) * f * gh / 2
    return (sx, sy, depth)


def _rot_x(pts, a):
    c, s = math.cos(a), math.sin(a)
    return [(x, y * c - z * s, y * s + z * c) for x, y, z in pts]


def _rot_z(pts, a):
    c, s = math.cos(a), math.sin(a)
    return [(x * c - y * s, x * s + y * c, z) for x, y, z in pts]


class MarkerArrowOverlay(QWidget):
    _SIZE = 100
    _BG = QColor(0, 0, 0, 100)
    _SEGS = 12
    _TILT = math.radians(30)
    _CAM_D = 2.2

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self._SIZE, self._SIZE)
        self.show()
        hwnd = int(self.winId())
        cur = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, cur | _CLICK_THROUGH)
        self.hide()

        self._yaw_d = 0.0
        self._pitch_d = 0.0
        self._dist_text = ""

        n = self._SEGS
        self._base_ring = [(0.3 * math.cos(2 * math.pi * i / n),
                            -0.45,
                            0.3 * math.sin(2 * math.pi * i / n)) for i in range(n)]
        self._tip = (0.0, 0.85, 0.0)

        NR = 48
        self._eq_ring = [(math.cos(2 * math.pi * i / NR),
                          math.sin(2 * math.pi * i / NR), 0.0) for i in range(NR)]
        self._mer_ring = [(0.0, math.cos(2 * math.pi * i / NR),
                           math.sin(2 * math.pi * i / NR)) for i in range(NR)]

    def update_arrow(self, yaw_delta, pitch_delta, dist, game_rect):
        self._yaw_d = yaw_delta
        self._pitch_d = pitch_delta
        self._dist_text = f"{dist:.0f}" if dist >= 1 else f"{dist:.1f}"
        if game_rect:
            gx, gy, gw, _gh = game_rect
            self.move(gx + (gw - self._SIZE) // 2, gy + 10)
        if not self.isVisible():
            self.show()
        self.update()

    def _proj(self, x, y, z, cx, cy, R):
        pz = z + self._CAM_D
        if pz < 0.01:
            pz = 0.01
        f = self._CAM_D
        return (cx + x * R * f / pz,
                cy - y * R * f / pz,
                z)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        S = self._SIZE
        cx, cy = S / 2, S / 2 - 4
        R = S / 2 - 8

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(self._BG))
        p.drawEllipse(QPointF(cx, cy), R, R)

        TILT = self._TILT
        yr = math.radians(self._yaw_d)
        pr = math.radians(self._pitch_d)

        ring_pen_front = QPen(QColor(255, 255, 255, 50), 0.8)
        ring_pen_back = QPen(QColor(255, 255, 255, 18), 0.5)
        for ring_3d in (self._eq_ring, self._mer_ring):
            tilted = _rot_x(ring_3d, TILT)
            nr = len(tilted)
            for i in range(nr):
                j = (i + 1) % nr
                z_avg = (tilted[i][2] + tilted[j][2]) / 2
                p.setPen(ring_pen_front if z_avg > -0.05 else ring_pen_back)
                a2 = self._proj(*tilted[i], cx, cy, R)
                b2 = self._proj(*tilted[j], cx, cy, R)
                p.drawLine(QPointF(a2[0], a2[1]), QPointF(b2[0], b2[1]))

        all_pts = list(self._base_ring) + [self._tip]
        all_pts = _rot_x(all_pts, pr)
        all_pts = _rot_z(all_pts, yr)
        all_pts = _rot_x(all_pts, TILT)

        n = self._SEGS
        proj_pts = [self._proj(*pt, cx, cy, R) for pt in all_pts]
        base_2d = proj_pts[:n]
        tip_2d = proj_pts[n]

        lx, ly, lz = 0.35, 0.65, 0.55
        ll = math.sqrt(lx * lx + ly * ly + lz * lz)
        lx /= ll; ly /= ll; lz /= ll

        faces = []
        for i in range(n):
            j = (i + 1) % n
            b0, b1, tp = all_pts[i], all_pts[j], all_pts[n]
            e1 = (b0[0] - tp[0], b0[1] - tp[1], b0[2] - tp[2])
            e2 = (b1[0] - tp[0], b1[1] - tp[1], b1[2] - tp[2])
            nx = e1[1] * e2[2] - e1[2] * e2[1]
            ny = e1[2] * e2[0] - e1[0] * e2[2]
            nz = e1[0] * e2[1] - e1[1] * e2[0]
            nl = math.sqrt(nx * nx + ny * ny + nz * nz)
            if nl < 1e-6:
                continue
            nx /= nl; ny /= nl; nz /= nl
            if nz < -0.02:
                continue
            diff = max(0.12, nx * lx + ny * ly + nz * lz)
            avg_z = (b0[2] + b1[2] + tp[2]) / 3
            faces.append((avg_z, i, j, diff))

        bc_local = (0.0, -0.45, 0.0)
        bc_world = _rot_x([bc_local], pr)
        bc_world = _rot_z(bc_world, yr)
        bc_world = _rot_x(bc_world, TILT)[0]
        draw_base = bc_world[2] > 0.05

        faces.sort(key=lambda f: -f[0])

        if draw_base:
            bp = QPolygonF([QPointF(bx, by) for bx, by, _ in base_2d])
            p.setPen(QPen(QColor(160, 140, 0, 80), 0.5))
            p.setBrush(QBrush(QColor(160, 140, 0, 140)))
            p.drawPolygon(bp)

        for _, i, j, diff in faces:
            rc = min(255, int(255 * diff))
            gc = min(255, int(240 * diff))
            bc_ = min(255, int(50 * diff))
            col = QColor(rc, gc, bc_, 220)
            tri = QPolygonF([
                QPointF(tip_2d[0], tip_2d[1]),
                QPointF(base_2d[i][0], base_2d[i][1]),
                QPointF(base_2d[j][0], base_2d[j][1]),
            ])
            p.setPen(QPen(col.darker(130), 0.3))
            p.setBrush(QBrush(col))
            p.drawPolygon(tri)

        p.setPen(QColor(255, 255, 255, 200))
        p.setFont(pixel_font(13))
        p.drawText(QRectF(0, S - 16, S, 16),
                   Qt.AlignHCenter | Qt.AlignTop, self._dist_text)
        p.end()


class MarkerWorldOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.show()
        hwnd = int(self.winId())
        cur = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, cur | _CLICK_THROUGH)
        self.hide()

        self._sx = 0.0
        self._sy = 0.0
        self._radius = 10.0

    def update_marker(self, sx, sy, depth, game_rect):
        gx, gy, gw, gh = game_rect
        geo = self.geometry()
        if geo.x() != gx or geo.y() != gy or geo.width() != gw or geo.height() != gh:
            self.setGeometry(gx, gy, gw, gh)
        self._sx = sx
        self._sy = sy
        self._radius = max(4, min(30, 200 / max(depth, 1)))
        if not self.isVisible():
            self.show()
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        r = self._radius
        cx, cy = self._sx, self._sy

        p.setPen(QPen(QColor(255, 255, 0, 200), 2))
        p.setBrush(QBrush(QColor(255, 255, 0, 40)))
        p.drawEllipse(QPointF(cx, cy), r, r)

        p.setPen(QPen(QColor(255, 255, 0, 150), 1))
        g = r + 5
        p.drawLine(QPointF(cx - g, cy), QPointF(cx - r + 2, cy))
        p.drawLine(QPointF(cx + r - 2, cy), QPointF(cx + g, cy))
        p.drawLine(QPointF(cx, cy - g), QPointF(cx, cy - r + 2))
        p.drawLine(QPointF(cx, cy + r - 2), QPointF(cx, cy + g))

        p.end()
