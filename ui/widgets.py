import os

from PyQt5.QtWidgets import QWidget, QPushButton, QHBoxLayout
from PyQt5.QtCore import Qt, QRectF, pyqtSignal, pyqtProperty, QPropertyAnimation, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QPixmap, QTransform
from PyQt5.QtSvg import QSvgRenderer

from utils import resource_path

_ICONS_DIR = resource_path("icons")

_renderers: dict[str, QSvgRenderer] = {}


def _svg(name: str) -> QSvgRenderer | None:
    if name not in _renderers:
        path = os.path.join(_ICONS_DIR, f"{name}.svg")
        if os.path.isfile(path):
            _renderers[name] = QSvgRenderer(path)
        else:
            _renderers[name] = None
    return _renderers[name]


class IconWidget(QWidget):
    """Draws icons: close, minimize, telegram, gta5 (SVG-based with color tint)."""

    ICON_COLOR = QColor(180, 180, 180)

    def __init__(self, icon_type, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self._color = None

    def set_color(self, color: QColor):
        if self._color != color:
            self._color = color
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        m = round(w * 0.3)
        stroke = 1.8

        if self.icon_type == "close":
            painter.setPen(QPen(self.ICON_COLOR, stroke))
            painter.drawLine(m, m, w - m, h - m)
            painter.drawLine(w - m, m, m, h - m)

        elif self.icon_type == "minimize":
            painter.setPen(QPen(self.ICON_COLOR, stroke))
            y = h // 2
            painter.drawLine(m, y, w - m, y)

        else:
            color = self._color or self.ICON_COLOR
            renderer = _svg(self.icon_type)
            if renderer and renderer.isValid():
                pix = QPixmap(w, h)
                pix.fill(Qt.transparent)
                p2 = QPainter(pix)
                renderer.render(p2, QRectF(0, 0, w, h))
                p2.setCompositionMode(QPainter.CompositionMode_SourceIn)
                p2.fillRect(0, 0, w, h, color)
                p2.end()
                painter.drawPixmap(0, 0, pix)

        painter.end()


class SpinningIconWidget(IconWidget):
    """IconWidget with optional spinning animation (for update status)."""

    def __init__(self, icon_type, parent=None):
        super().__init__(icon_type, parent)
        self._angle = 0.0
        self._spinning = False

        self._anim = QPropertyAnimation(self, b"rotation")
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(360.0)
        self._anim.setDuration(1200)
        self._anim.setLoopCount(-1)

    def _get_rotation(self):
        return self._angle

    def _set_rotation(self, val):
        self._angle = val
        self.update()

    rotation = pyqtProperty(float, _get_rotation, _set_rotation)

    def start_spin(self):
        if not self._spinning:
            self._spinning = True
            self._anim.start()

    def stop_spin(self):
        if self._spinning:
            self._spinning = False
            self._anim.stop()
            self._angle = 0.0
            self.update()

    def paintEvent(self, event):
        if not self._spinning:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        painter.translate(cx, cy)
        painter.rotate(self._angle)
        painter.translate(-cx, -cy)

        w, h = self.width(), self.height()
        color = self._color or self.ICON_COLOR
        renderer = _svg(self.icon_type)
        if renderer and renderer.isValid():
            pix = QPixmap(w, h)
            pix.fill(Qt.transparent)
            p2 = QPainter(pix)
            renderer.render(p2, QRectF(0, 0, w, h))
            p2.setCompositionMode(QPainter.CompositionMode_SourceIn)
            p2.fillRect(0, 0, w, h, color)
            p2.end()
            painter.drawPixmap(0, 0, pix)

        painter.end()


class TitleButton(QPushButton):
    def __init__(self, icon_type, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton { background: transparent; border: none; }
            QPushButton:hover { background: rgba(255, 255, 255, 15); }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._icon = IconWidget(icon_type)
        layout.addWidget(self._icon)


class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None, checked=False):
        super().__init__(parent)
        self._checked = checked
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self):
        return self._checked

    def setChecked(self, val):
        if val != self._checked:
            self._checked = val
            self.update()
            self.toggled.emit(self._checked)

    def mousePressEvent(self, event):
        self.setChecked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad = 3  # padding between track edge and thumb

        # track — full widget area, pill shape
        r = h / 2
        p.setPen(Qt.NoPen)
        if self._checked:
            p.setBrush(QColor(80, 200, 80))
        else:
            p.setBrush(QColor(60, 60, 65))
            # subtle border when off
            p.setPen(QPen(QColor(90, 90, 95), 1.5))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # thumb — circle with slight shadow
        p.setPen(Qt.NoPen)
        thumb_d = h - pad * 2
        thumb_y = pad
        thumb_x = (w - thumb_d - pad) if self._checked else pad
        # shadow
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(thumb_x + 0.5, thumb_y + 1, thumb_d, thumb_d))
        # thumb
        p.setBrush(QColor(240, 240, 240))
        p.drawEllipse(QRectF(thumb_x, thumb_y, thumb_d, thumb_d))

        p.end()
