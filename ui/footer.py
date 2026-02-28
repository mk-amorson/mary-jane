"""Footer bar with background progress indicator."""

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor, QPen


class FooterBar(QWidget):
    _BG   = QColor(20, 20, 24, 230)
    _FILL = QColor(80, 200, 80, 40)
    _BORDER_TOP = QColor(255, 255, 255, 15)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self._progress = 0.0

    def set_progress(self, value):
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(Qt.NoPen)
        p.setBrush(self._BG)
        p.drawRect(0, 0, w, h)

        bw = int(w * self._progress)
        if bw > 0:
            p.setBrush(self._FILL)
            p.drawRect(0, 0, bw, h)

        p.setPen(QPen(self._BORDER_TOP, 1))
        p.drawLine(0, 0, w, 0)

        p.end()
