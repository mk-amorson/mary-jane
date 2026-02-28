"""Stash timer widgets and schedules."""

import ctypes
from datetime import datetime, timezone, timedelta

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QApplication
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPainter, QColor, QPen

from ui.styles import pixel_font, COLOR_RED, COLOR_GREEN
from ui.widgets import IconWidget

_MSK = timezone(timedelta(hours=3))
_DAY = 86400

STASHES = [
    ("gear",    [1,3,5,7,9,11,13,15,17,19,21,23], 15, 20),   # Mechanical
    ("flask",   [1,3,5,7,9,11,13,15,17,19,21,23], 30, 20),   # Chemical
    ("factory", [1,3,5,7,9,11,13,15,17,19,21,23], 45, 20),   # Industrial
    ("warning", [2,6,10,14,18,22],                  0,  5),   # Danger zone
]

# ── Win32 constants ──
_GWL_EXSTYLE      = -20
_WS_EX_LAYERED    = 0x80000
_WS_EX_TRANSPARENT = 0x20
_WS_EX_TOOLWINDOW = 0x80
_CLICK_THROUGH    = _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW


def stash_status(hours, open_min, dur_min):
    now = datetime.now(_MSK)
    cur = now.hour * 3600 + now.minute * 60 + now.second

    for h in hours:
        o = h * 3600 + open_min * 60
        c = o + dur_min * 60
        if c > _DAY:
            cw = c - _DAY
            if cur >= o:
                return True, (_DAY - cur) + cw
            if cur < cw:
                return True, cw - cur
        elif o <= cur < c:
            return True, c - cur

    best = None
    for h in hours:
        o = h * 3600 + open_min * 60
        w = o - cur if o > cur else (_DAY - cur) + o
        if best is None or w < best:
            best = w
    return False, best


def fmt_time(sec):
    sec = max(0, int(sec))
    if sec >= 3600:
        h, r = divmod(sec, 3600)
        m, s = divmod(r, 60)
        return f"{h}:{m:02d}:{s:02d}"
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"


class StashTimerWidget(QWidget):
    _BG      = QColor(255, 255, 255, 10)
    _FILL_G  = QColor(80, 200, 80, 90)
    _FILL_R  = QColor(200, 70, 70, 90)

    def __init__(self, icon_name, hours, open_min, dur_min, parent=None):
        super().__init__(parent)
        self._hours = hours
        self._open_min = open_min
        self._dur = dur_min
        self._is_open = False
        self._progress = 0.0
        self._secs_left = 0
        self._was_open = False
        self._just_opened = False

        self._open_sec = dur_min * 60
        cycle = (hours[1] - hours[0]) * 3600 if len(hours) >= 2 else _DAY
        self._closed_sec = cycle - self._open_sec

        lay = QHBoxLayout(self)
        lay.setContentsMargins(7, 1, 7, 1)
        lay.setSpacing(5)

        self._icon = IconWidget(icon_name)
        self._icon.setFixedSize(21, 21)
        self._icon.set_color(QColor(255, 255, 255))
        lay.addWidget(self._icon)

        lay.addStretch()

        self._time = QLabel("--:--")
        self._time.setFont(pixel_font(19))
        self._time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._time.setStyleSheet("color: white;")
        lay.addWidget(self._time)

    @property
    def is_relevant(self):
        return self._is_open or self._secs_left <= 180

    def refresh(self):
        is_open, secs = stash_status(self._hours, self._open_min, self._dur)
        self._secs_left = secs
        self._time.setText(fmt_time(secs))
        self._is_open = is_open
        if is_open and not self._was_open:
            self._just_opened = True
        self._was_open = is_open
        total = self._open_sec if is_open else self._closed_sec
        self._progress = (1.0 - secs / total) if total else 1.0
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = 5

        p.setPen(Qt.NoPen)
        p.setBrush(self._BG)
        p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

        bw = int((w - 2) * max(0.0, min(1.0, self._progress)))
        if bw > 0:
            p.setBrush(self._FILL_G if self._is_open else self._FILL_R)
            p.drawRoundedRect(1, 1, bw, h - 2, r, r)

        color = COLOR_GREEN if self._is_open else COLOR_RED
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(color, 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        p.end()


class StashFloatWindow(QWidget):
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

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(12)

        self._items = []
        for name, *_ in STASHES:
            icon = IconWidget(name)
            icon.setFixedSize(21, 21)
            icon.set_color(QColor(255, 255, 255))
            lbl = QLabel("--:--")
            lbl.setFont(pixel_font(19))
            lbl.setStyleSheet("color: white;")
            lay.addWidget(icon)
            lay.addWidget(lbl)
            icon.hide()
            lbl.hide()
            self._items.append((icon, lbl))

    def update_timers(self, stash_widgets):
        any_visible = False
        for i, w in enumerate(stash_widgets):
            icon, lbl = self._items[i]
            if w.is_relevant:
                icon.show()
                lbl.show()
                lbl.setText(w._time.text())
                c = "rgb(80,200,80)" if w._is_open else "white"
                lbl.setStyleSheet(f"color: {c};")
                any_visible = True
            else:
                icon.hide()
                lbl.hide()
        if any_visible:
            self.adjustSize()
            scr = QApplication.primaryScreen().geometry()
            self.move((scr.width() - self.width()) // 2, 0)
            if not self.isVisible():
                self.show()
        elif self.isVisible():
            self.hide()
