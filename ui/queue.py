"""Queue ETA widget with progress bar."""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPainter, QColor, QPen

from ui.styles import pixel_font, COLOR_GREEN
from ui.stash import fmt_time


class QueueETAWidget(QWidget):
    _BG     = QColor(255, 255, 255, 10)
    _FILL   = QColor(80, 200, 80, 90)

    _BLEND = 0.2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0.0
        self._eta_display = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(7, 1, 7, 1)
        lay.setSpacing(5)
        lay.addStretch()

        self._time = QLabel("")
        self._time.setFont(pixel_font(19))
        self._time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._time.setStyleSheet("color: white;")
        lay.addWidget(self._time)

    def refresh(self, state):
        self._progress = max(0.0, min(1.0, state.queue_progress))
        eta = state.queue_eta_seconds
        if eta is not None and eta >= 0:
            if self._eta_display is not None and self._eta_display > 0:
                counted = self._eta_display - 1
                self._eta_display = (1 - self._BLEND) * counted + self._BLEND * eta
                self._eta_display = max(0.0, self._eta_display)
            else:
                self._eta_display = eta
            self._time.setText(fmt_time(self._eta_display))
        else:
            self._eta_display = None
            self._time.setText("")
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
            p.setBrush(self._FILL)
            p.drawRoundedRect(1, 1, bw, h - 2, r, r)

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(COLOR_GREEN, 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        p.end()
