import os
import io
import ctypes
import time as _time
from datetime import datetime, timezone, timedelta

import asyncio
from PIL import Image as PILImage

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QApplication, QStackedWidget, QLineEdit,
    QScrollArea, QComboBox, QSizePolicy,
)
from PyQt5.QtCore import (
    Qt, QTimer, QRectF, QPointF, QUrl, QByteArray, pyqtSignal,
    pyqtProperty, QPropertyAnimation, QEasingCurve, QObject, QEvent,
)
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QFont, QFontDatabase, QPolygonF, QPixmap,
)
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

from core import is_game_running
from utils import resource_path
from ui.widgets import IconWidget, TitleButton, ToggleSwitch
from modules.marketplace.parser import (
    SERVERS as MP_SERVERS, CATEGORIES as MP_CATEGORIES,
)
from modules.marketplace import database as mp_db

# ── Click Sound ──

_SOUND_DIR = resource_path("sounds")
_CLICK_SOUND = os.path.join(_SOUND_DIR, "click.mp3")
_click_player: QMediaPlayer | None = None


def _init_click_sound():
    global _click_player
    if _click_player is not None:
        return
    _click_player = QMediaPlayer()
    _click_player.setVolume(70)


def play_click():
    if _click_player is None:
        _init_click_sound()
    _click_player.stop()
    _click_player.setMedia(QMediaContent(QUrl.fromLocalFile(_CLICK_SOUND)))
    _click_player.play()


# Interactive widget types that trigger click sound
_CLICK_TYPES = (
    QPushButton, QComboBox, QLineEdit,
)


class _ClickSoundFilter(QObject):
    """App-wide event filter that plays click sound on interactive widgets."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if isinstance(obj, _CLICK_TYPES):
                play_click()
            elif type(obj).__name__ in ("ToggleSwitch", "TitleButton",
                                         "ItemRowWidget", "SellItemRowWidget",
                                         "_StarWidget"):
                play_click()
        return False


# ── Fonts ──

_FONT_DIR = resource_path("fonts")
_FONTS = {
    "app":   os.path.join(_FONT_DIR, "GTA Russian.ttf"),
    "pixel": os.path.join(_FONT_DIR, "web_ibm_mda.ttf"),
}
_font_families: dict[str, str | None] = {"app": None, "pixel": None}


def _load_fonts():
    for key, path in _FONTS.items():
        if os.path.isfile(path) and _font_families[key] is None:
            fid = QFontDatabase.addApplicationFont(path)
            if fid >= 0:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    _font_families[key] = fams[0]


def _make_font(key: str, size: int) -> QFont:
    family = _font_families.get(key)
    f = QFont(family) if family else QFont("Consolas" if key == "pixel" else "")
    f.setPixelSize(size)
    return f


def app_font(size: int) -> QFont:
    return _make_font("app", size)


def pixel_font(size: int) -> QFont:
    return _make_font("pixel", size)


# ── Colors ──

COLOR_RED    = QColor(200, 70, 70)
COLOR_YELLOW = QColor(220, 180, 50)
COLOR_GREEN  = QColor(80, 200, 80)

# ── Win32 constants ──

_GWL_EXSTYLE      = -20
_WS_EX_LAYERED    = 0x80000
_WS_EX_TRANSPARENT = 0x20
_WS_EX_TOOLWINDOW = 0x80
_CLICK_THROUGH    = _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW

# ── Stash schedules (Moscow time) ──

_MSK = timezone(timedelta(hours=3))
_DAY = 86400

STASHES = [
    ("gear",    [1,3,5,7,9,11,13,15,17,19,21,23], 15, 20),   # Mechanical
    ("flask",   [1,3,5,7,9,11,13,15,17,19,21,23], 30, 20),   # Chemical
    ("factory", [1,3,5,7,9,11,13,15,17,19,21,23], 45, 20),   # Industrial
    ("warning", [2,6,10,14,18,22],                  0,  5),   # Danger zone
]

# ── Cached stylesheets ──

_btn_css = None
_input_css = None


def _button_style():
    global _btn_css
    if _btn_css is None:
        ff = f"font-family: '{_font_families['app']}';" if _font_families["app"] else ""
        _btn_css = f"""
            QPushButton {{
                background: rgb(32,32,38); color: rgb(240,240,240);
                border: 1px solid rgba(255,255,255,20); border-radius: 5px;
                padding: 5px; font-size: 27px; {ff}
            }}
            QPushButton:hover {{ background: rgb(44,44,52); }}
        """
    return _btn_css


def _input_style():
    global _input_css
    if _input_css is None:
        ff = f"font-family: '{_font_families['app']}';" if _font_families["app"] else ""
        _input_css = f"""
            QLineEdit {{
                background: rgb(32,32,38); color: rgb(240,240,240);
                border: 1px solid rgba(255,255,255,20); border-radius: 5px;
                padding: 3px; font-size: 27px; {ff}
            }}
            QLineEdit:disabled {{
                color: rgb(120,120,120); background: rgb(28,28,34);
            }}
        """
    return _input_css


_combo_css = None


def _combo_style():
    global _combo_css
    if _combo_css is None:
        ff = f"font-family: '{_font_families['app']}';" if _font_families["app"] else ""
        _combo_css = f"""
            QComboBox {{
                background: rgb(32,32,38); color: rgb(240,240,240);
                border: 1px solid rgba(255,255,255,20); border-radius: 5px;
                padding: 5px; font-size: 27px; {ff}
            }}
            QComboBox:hover {{ background: rgb(44,44,52); }}
            QComboBox::drop-down {{ border: none; width: 0px; }}
            QComboBox::down-arrow {{ width: 0; height: 0; }}
            QComboBox QLineEdit {{
                background: transparent; color: rgb(240,240,240);
                border: none; font-size: 27px; {ff}
                selection-background-color: transparent;
            }}
            QComboBox QAbstractItemView {{
                background: rgb(32,32,38); color: rgb(240,240,240);
                selection-background-color: rgb(50,50,60);
                border: 1px solid rgba(255,255,255,20);
                outline: none; font-size: 20px;
            }}
            QComboBox QAbstractItemView QScrollBar:vertical {{ width: 0px; }}
        """
    return _combo_css


_SCROLL_CSS = """
    QScrollArea { background: transparent; border: none; }
    QWidget#mp_list { background: transparent; }
    QScrollBar:vertical { width: 0px; }
    QScrollBar:horizontal { height: 0px; }
"""


class _CenteredCombo(QComboBox):
    """QComboBox with center-aligned display text."""

    def paintEvent(self, _ev):
        from PyQt5.QtWidgets import QStylePainter, QStyleOptionComboBox
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        text = opt.currentText
        opt.currentText = ""
        p.drawComplexControl(p.style().CC_ComboBox, opt)
        p.setPen(QColor(240, 240, 240))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignCenter, text)


def _fmt_price(n):
    if not n or n <= 0:
        return "\u2014"
    return "$" + f"{n:,}".replace(",", " ")


def _date_color(date_str: str | None) -> QColor:
    """Return color based on how old a date string is.

    Blue (>1 day), Yellow (1h-1d), Green (<1h).
    """
    if not date_str:
        return QColor(100, 180, 255)  # blue — unknown age
    try:
        from datetime import datetime, timezone
        # Try ISO format first (from server)
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            # Old format: "DD.MM.YYYY HH:MM"
            dt = datetime.strptime(date_str, "%d.%m.%Y %H:%M")
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age = (now - dt).total_seconds()
        if age < 3600:
            return QColor(80, 255, 80)    # green
        elif age < 86400:
            return QColor(255, 200, 50)   # yellow
        else:
            return QColor(100, 180, 255)  # blue
    except Exception:
        return QColor(100, 180, 255)


# ── Stash helpers ──

def _stash_status(hours, open_min, dur_min):
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


def _fmt_time(sec):
    sec = max(0, int(sec))
    if sec >= 3600:
        h, r = divmod(sec, 3600)
        m, s = divmod(r, 60)
        return f"{h}:{m:02d}:{s:02d}"
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"


# ══════════════════════════════════════════════════════════════
#  Overlay  — debug rectangle over game window
# ══════════════════════════════════════════════════════════════

class OverlayWindow(QWidget):
    _PEN = QPen(QColor(255, 255, 0), 2)
    _BRUSH = QColor(255, 255, 0, 25)

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
        gr, nr = s.game_rect, s.ocr_number_region

        show_queue = gr and s.queue_search_active and (s.ocr_text_region or nr)
        show_fish = s.fishing_active and s.fishing_step in ("init", "cast", "strike", "reel", "take") and gr
        show_sell = s.sell_active and gr and (s.sell_match_rect or s.sell_item_click)

        if show_queue or show_fish or show_sell:
            gx, gy, gw, gh = gr
            geo = self.geometry()
            if geo.x() != gx or geo.y() != gy or geo.width() != gw or geo.height() != gh:
                self.setGeometry(gx, gy, gw, gh)
            if not self.isVisible():
                self.show()
            snap = (gr, s.ocr_text_region, nr, s.queue_position,
                    s.fishing_step, s.fishing_squares,
                    s.fishing_bar_rect,
                    s.fishing_green_zone, s.fishing_slider_x,
                    s.fishing_space_icon,
                    s.fishing_bobber_rect, s.fishing_bubbles,
                    s.fishing_ad_icon, s.fishing_camera_dir,
                    s.fishing_take_icon,
                    s.sell_active, s.sell_match_rect,
                    s.sell_match_name, s.sell_item_click)
            if snap != self._snap:
                self._snap = snap
                self.update()
        elif self.isVisible():
            self.hide()
            self._snap = None

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        nr = self._state.ocr_number_region
        if nr and self._state.queue_search_active:
            p.setPen(self._PEN)
            p.setBrush(self._BRUSH)
            p.drawRect(*nr)

        self._paint_fishing(p)
        self._paint_sell(p)
        p.end()

    def _paint_fishing(self, p: QPainter):
        s = self._state
        step = s.fishing_step

        # squares kept for internal use but hidden from overlay
        # squares = s.fishing_squares

        if step == "cast":
            # slider bar: yellow
            bar = s.fishing_bar_rect
            if bar:
                bx, by, bw, bh = bar
                p.setPen(QPen(QColor(255, 255, 0), 2))
                p.setBrush(QColor(255, 255, 0, 20))
                p.drawRect(bx, by, bw, bh)

            # green zone
            gz = s.fishing_green_zone
            if gz:
                gx, gy, gw, gh = gz
                p.setPen(QPen(QColor(80, 255, 80), 2))
                p.setBrush(QColor(80, 255, 80, 40))
                p.drawRect(gx, gy, gw, gh)

            # slider: red line
            sx = s.fishing_slider_x
            if sx is not None and bar:
                bx, by, bw, bh = bar
                p.setPen(QPen(QColor(255, 60, 60), 2))
                p.drawLine(sx, by, sx, by + bh)

            # space icon
            sp = s.fishing_space_icon
            if sp:
                spx, spy, spw, sph = sp
                p.setPen(QPen(QColor(80, 255, 80), 2))
                p.setBrush(QColor(80, 255, 80, 30))
                p.drawRect(spx, spy, spw, sph)

        elif step == "strike":
            bob = s.fishing_bobber_rect
            if bob:
                bx, by, bw, bh = bob
                if s.fishing_bubbles:
                    p.setPen(QPen(QColor(255, 165, 0), 3))
                    p.setBrush(QColor(255, 165, 0, 30))
                else:
                    p.setPen(QPen(QColor(255, 80, 255), 2))
                    p.setBrush(QColor(255, 80, 255, 20))
                p.drawRect(bx, by, bw, bh)

        elif step == "reel":
            ad = s.fishing_ad_icon
            if ad:
                ax, ay, aw, ah = ad
                p.setPen(QPen(QColor(0, 200, 255), 2))
                p.setBrush(QColor(0, 200, 255, 30))
                p.drawRect(ax, ay, aw, ah)

        elif step == "take":
            tk = s.fishing_take_icon
            if tk:
                tx, ty, tw, th = tk
                p.setPen(QPen(QColor(255, 220, 50), 2))
                p.setBrush(QColor(255, 220, 50, 30))
                p.drawRect(tx, ty, tw, th)

    # ── sell overlay colors by template name ──
    _SELL_COLORS = {
        "items":       QColor(0, 200, 255),    # cyan
        "item_search": QColor(255, 165, 0),    # orange
        "create":      QColor(80, 255, 80),    # green
        "item_name":   QColor(255, 220, 50),   # gold
        "item_count":  QColor(255, 80, 255),   # magenta
        "set_price":   QColor(100, 180, 255),  # light blue
        "place_order": QColor(255, 100, 100),  # red
    }

    def _paint_sell(self, p: QPainter):
        s = self._state
        if not s.sell_active:
            return

        rect = s.sell_match_rect
        name = s.sell_match_name
        if rect:
            rx, ry, rw, rh = rect
            color = self._SELL_COLORS.get(name, QColor(255, 255, 0))
            p.setPen(QPen(color, 2))
            p.setBrush(QColor(color.red(), color.green(), color.blue(), 30))
            p.drawRect(rx, ry, rw, rh)

        click = s.sell_item_click
        if click and name == "item_name":
            cx, cy = click
            color = self._SELL_COLORS["item_name"]
            p.setPen(QPen(color, 2))
            p.setBrush(QColor(color.red(), color.green(), color.blue(), 40))
            p.drawEllipse(cx - 12, cy - 12, 24, 24)


# ══════════════════════════════════════════════════════════════
#  StashTimerWidget — row with progress bar + text overlay
# ══════════════════════════════════════════════════════════════

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

    def refresh(self):
        is_open, secs = _stash_status(self._hours, self._open_min, self._dur)
        self._time.setText(_fmt_time(secs))
        self._is_open = is_open
        total = self._open_sec if is_open else self._closed_sec
        self._progress = (1.0 - secs / total) if total else 1.0
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = 5

        # track
        p.setPen(Qt.NoPen)
        p.setBrush(self._BG)
        p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

        # fill
        bw = int((w - 2) * max(0.0, min(1.0, self._progress)))
        if bw > 0:
            p.setBrush(self._FILL_G if self._is_open else self._FILL_R)
            p.drawRoundedRect(1, 1, bw, h - 2, r, r)

        # border
        color = COLOR_GREEN if self._is_open else COLOR_RED
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(color, 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        p.end()


# ══════════════════════════════════════════════════════════════
#  QueueETAWidget — progress bar with estimated time
# ══════════════════════════════════════════════════════════════

class QueueETAWidget(QWidget):
    _BG     = QColor(255, 255, 255, 10)
    _FILL   = QColor(80, 200, 80, 90)

    _BLEND = 0.2    # how fast display catches up to target ETA

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0.0
        self._eta_display = None   # smoothed value shown to user

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
                # natural countdown (-1s) then blend towards real ETA
                counted = self._eta_display - 1
                self._eta_display = (1 - self._BLEND) * counted + self._BLEND * eta
                self._eta_display = max(0.0, self._eta_display)
            else:
                self._eta_display = eta
            self._time.setText(_fmt_time(self._eta_display))
        else:
            self._eta_display = None
            self._time.setText("")
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = 5

        # track
        p.setPen(Qt.NoPen)
        p.setBrush(self._BG)
        p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

        # fill
        bw = int((w - 2) * max(0.0, min(1.0, self._progress)))
        if bw > 0:
            p.setBrush(self._FILL)
            p.drawRoundedRect(1, 1, bw, h - 2, r, r)

        # border
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(COLOR_GREEN, 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        p.end()


# ══════════════════════════════════════════════════════════════
#  MarketplaceProgressWidget — parsing progress bar
# ══════════════════════════════════════════════════════════════

class MarketplaceProgressWidget(QWidget):
    _BG   = QColor(255, 255, 255, 10)
    _FILL = QColor(80, 200, 80, 90)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0.0
        self._pct_text = ""
        self._eta_text = ""
        self.setFixedHeight(36)

    def set_progress(self, progress, done, total, start_time):
        self._progress = max(0.0, min(1.0, progress))
        pct = int(progress * 100)
        self._pct_text = f"{pct}%"
        # ETA
        if done > 0 and total > done and start_time > 0:
            import time as _t
            elapsed = _t.monotonic() - start_time
            rate = done / elapsed
            remaining = (total - done) / rate
            secs = max(0, int(remaining))
            m, s = divmod(secs, 60)
            self._eta_text = f"{m:02d}:{s:02d}"
        else:
            self._eta_text = ""
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = 5

        p.setPen(Qt.NoPen)
        p.setBrush(self._BG)
        p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

        bw = int((w - 2) * self._progress)
        if bw > 0:
            p.setBrush(self._FILL)
            p.drawRoundedRect(1, 1, bw, h - 2, r, r)

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(COLOR_GREEN, 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        p.setPen(QColor(255, 255, 255))
        p.setFont(pixel_font(19))
        if self._pct_text:
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, self._pct_text)
        if self._eta_text:
            p.drawText(QRectF(0, 0, w - 8, h), Qt.AlignRight | Qt.AlignVCenter, self._eta_text)

        p.end()


# ══════════════════════════════════════════════════════════════
#  ThumbLoader — throttled thumbnail downloader
# ══════════════════════════════════════════════════════════════

_COL_IMG   = 80
_COL_PRICE = 190

# Pixmap cache: item_id → scaled QPixmap  (survives list rebuilds)
_thumb_cache: dict[int, QPixmap] = {}

_THUMB_URL = "https://cdn.majestic-files.net/public/master/static/img/inventory/items/{}.webp"
_THUMB_SZ = _COL_IMG
_MAX_CONCURRENT = 20


class _ThumbLoader:
    """Throttled thumbnail downloader. Limits concurrent requests."""

    def __init__(self, nam: QNetworkAccessManager):
        self._nam = nam
        self._queue: list[tuple[int, QLabel]] = []   # (item_id, label)
        self._active = 0
        self._replies: list = []   # track in-flight QNetworkReply

    def request(self, item_id: int, label: QLabel):
        if item_id in _thumb_cache:
            label.setPixmap(_thumb_cache[item_id])
            return
        self._queue.append((item_id, label))
        self._flush()

    def cancel_all(self):
        self._queue.clear()
        # abort all in-flight requests
        for r in self._replies:
            try:
                r.abort()
            except RuntimeError:
                pass
        self._replies.clear()
        self._active = 0

    def _flush(self):
        while self._queue and self._active < _MAX_CONCURRENT:
            iid, lbl = self._queue.pop(0)
            try:
                lbl.isVisible()
            except RuntimeError:
                continue
            if iid in _thumb_cache:
                lbl.setPixmap(_thumb_cache[iid])
                continue
            self._active += 1
            req = QNetworkRequest(QUrl(_THUMB_URL.format(iid)))
            req.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
            reply = self._nam.get(req)
            self._replies.append(reply)
            reply.finished.connect(lambda r=reply, i=iid, l=lbl: self._on_done(r, i, l))

    def _on_done(self, reply, iid, lbl):
        self._active = max(0, self._active - 1)
        try:
            self._replies.remove(reply)
        except ValueError:
            pass
        try:
            if reply.error() == reply.NoError:
                raw = bytes(reply.readAll())
                pm = QPixmap()
                if not pm.loadFromData(raw):
                    img = PILImage.open(io.BytesIO(raw)).convert("RGBA")
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    pm.loadFromData(QByteArray(buf.getvalue()))
                if not pm.isNull():
                    scaled = pm.scaled(_THUMB_SZ, _THUMB_SZ,
                                       Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    _thumb_cache[iid] = scaled
                    try:
                        lbl.setPixmap(scaled)
                    except RuntimeError:
                        pass
        except Exception:
            pass
        reply.deleteLater()
        self._flush()


# ══════════════════════════════════════════════════════════════
#  Favorites persistence
# ══════════════════════════════════════════════════════════════

def _load_favorites() -> set[int]:
    cfg = mp_db.load_config()
    return set(cfg.get("favorites", []))

def _save_favorites(fav: set[int]):
    cfg = mp_db.load_config()
    cfg["favorites"] = sorted(fav)
    mp_db.save_config(cfg)


# ══════════════════════════════════════════════════════════════
#  _StarWidget — clickable star with animated glow
# ══════════════════════════════════════════════════════════════

def _star_polygon(cx, cy, outer, inner, points=5):
    """Build a star QPolygonF centered at (cx, cy)."""
    import math
    pts = []
    for i in range(points * 2):
        r = outer if i % 2 == 0 else inner
        angle = math.pi / 2 + math.pi * i / points
        pts.append(QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle)))
    return QPolygonF(pts)


class _StarWidget(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, active=False, parent=None):
        super().__init__(parent)
        import random
        self._active = active
        self._glow = 1.0 if active else 0.0
        self._rng = random.Random()
        self.setFixedSize(48, 48)
        self.setCursor(Qt.PointingHandCursor)

        # glow in/out animation
        self._anim = QPropertyAnimation(self, b"glow_val")
        self._anim.setDuration(400)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        # bolt state
        self._bolts = []          # list of (points_list, born, duration)
        self._next_spawn = 0.0    # monotonic time for next batch

        self._bolt_timer = QTimer(self)
        self._bolt_timer.timeout.connect(self._bolt_tick)
        if active:
            self._bolt_timer.start(40)

    def _get_glow(self):
        return self._glow

    def _set_glow(self, v):
        self._glow = v
        self.update()

    glow_val = pyqtProperty(float, _get_glow, _set_glow)

    @property
    def active(self):
        return self._active

    @active.setter
    def active(self, val):
        if self._active != val:
            self._active = val
            self._anim.stop()
            self._anim.setStartValue(self._glow)
            self._anim.setEndValue(1.0 if val else 0.0)
            self._anim.start()
            if val:
                self._bolts.clear()
                self._next_spawn = 0.0
                self._bolt_timer.start(40)
            else:
                self._bolt_timer.stop()
                self._bolts.clear()
            self.toggled.emit(val)

    def _spawn_bolts(self):
        import math
        rng = self._rng
        sz = min(self.width(), self.height())
        cx, cy = sz / 2, sz / 2
        outer = sz * 0.28

        n = rng.randint(1, 3)
        tips = rng.sample(range(5), n)
        now = _time.monotonic()

        for tip_i in tips:
            tip_angle = math.pi / 2 + math.pi * 2 * tip_i / 5
            tip_x = cx + outer * math.cos(tip_angle)
            tip_y = cy - outer * math.sin(tip_angle)

            dx = tip_x - cx
            dy = tip_y - cy
            length = math.sqrt(dx * dx + dy * dy)
            nx, ny = dx / length, dy / length
            px, py = -ny, nx

            # main bolt: 3-6 jagged segments outward
            segs = rng.randint(3, 6)
            seg_len = rng.uniform(1.5, 3.0)
            points = [(tip_x, tip_y)]
            x, y = tip_x, tip_y
            for _ in range(segs):
                jitter = rng.uniform(-3.0, 3.0)
                x += nx * seg_len + px * jitter
                y += ny * seg_len + py * jitter
                points.append((x, y))

            duration = rng.uniform(0.10, 0.30)
            self._bolts.append((points, now, duration))

            # 60% chance of a branch from mid-point
            if rng.random() < 0.6 and len(points) >= 3:
                mid_idx = len(points) // 2
                bx, by = points[mid_idx]
                br_angle = rng.uniform(-0.8, 0.8)
                bnx = nx * math.cos(br_angle) - py * math.sin(br_angle)
                bny = ny * math.cos(br_angle) + px * math.sin(br_angle)
                bpx, bpy = -bny, bnx
                br_segs = rng.randint(2, 4)
                br_pts = [(bx, by)]
                bxx, byy = bx, by
                for _ in range(br_segs):
                    j = rng.uniform(-2.5, 2.5)
                    bxx += bnx * seg_len * 0.8 + bpx * j
                    byy += bny * seg_len * 0.8 + bpy * j
                    br_pts.append((bxx, byy))
                self._bolts.append((br_pts, now, duration))

    def _bolt_tick(self):
        now = _time.monotonic()
        # remove expired bolts
        self._bolts = [(pts, born, dur) for pts, born, dur in self._bolts
                       if now - born < dur]
        # spawn new batch if needed
        if now >= self._next_spawn:
            self._spawn_bolts()
            # find max duration of just-spawned bolts for pause calc
            if self._bolts:
                last_dur = self._bolts[-1][2]
            else:
                last_dur = 0.2
            self._next_spawn = now + last_dur + self._rng.uniform(0.05, 0.20)
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.active = not self._active
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        sz = min(self.width(), self.height())
        cx, cy = sz / 2, sz / 2
        outer = sz * 0.28
        inner = outer * 0.38

        g = self._glow  # 0..1

        # ── lightning bolts ──
        if self._active and g > 0.3:
            now = _time.monotonic()
            for points, born, dur in self._bolts:
                age = now - born
                if age > dur:
                    continue
                alpha = int(200 * g)
                pen = QPen(QColor(255, 215, 30, alpha), 1.5)
                p.setPen(pen)
                for j in range(len(points) - 1):
                    x1, y1 = points[j]
                    x2, y2 = points[j + 1]
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # ── main star outline ──
        star = _star_polygon(cx, cy, outer, inner)
        p.setBrush(Qt.NoBrush)
        base_alpha = 60
        active_alpha = 255
        alpha = int(base_alpha + (active_alpha - base_alpha) * g)
        pen_w = 1.8 + 0.7 * g
        p.setPen(QPen(QColor(255, 215, 0, alpha), pen_w))
        p.drawPolygon(star)

        p.end()


# ══════════════════════════════════════════════════════════════
#  ItemRowWidget — thumbnail + star + name + avg price, click-to-select
# ══════════════════════════════════════════════════════════════


class ItemRowWidget(QWidget):
    selectionChanged = pyqtSignal()
    favoriteChanged = pyqtSignal(int, bool)  # item_id, is_favorite

    def __init__(self, data, loader: _ThumbLoader, favorites: set[int], parent=None):
        super().__init__(parent)
        self.item_id = data[0]
        self.data = data
        self._selected = False
        iid = data[0]
        name = data[1]

        # Support both old format (10 cols) and new format (6 cols from sync)
        if len(data) >= 6 and len(data) <= 7:
            # New format: (id, name, category, last_price, median_7d, last_updated)
            last_price = data[3]
            median_7d = data[4]
            updated_at = data[5] if len(data) > 5 else None
        else:
            # Old format: (id, name, cat, avg, min, max, in_sale, sold, updated_at, source)
            last_price = data[3] if len(data) > 3 else 0
            median_7d = None
            updated_at = data[8] if len(data) > 8 else None

        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        # thumbnail
        self._thumb = QLabel()
        self._thumb.setFixedSize(_THUMB_SZ, _THUMB_SZ)
        self._thumb.setAlignment(Qt.AlignCenter)
        self._thumb.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._thumb)

        loader.request(iid, self._thumb)

        # star
        self._star = _StarWidget(active=iid in favorites)
        self._star.toggled.connect(lambda on: self.favoriteChanged.emit(self.item_id, on))
        lay.addWidget(self._star)

        # name + date column
        name_col = QWidget()
        name_col.setAttribute(Qt.WA_TransparentForMouseEvents)
        ncl = QVBoxLayout(name_col)
        ncl.setContentsMargins(0, 0, 0, 0)
        ncl.setSpacing(0)

        name_lbl = QLabel(name or "")
        name_lbl.setFont(app_font(32))
        name_lbl.setStyleSheet("color:rgb(200,200,200);")
        name_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        ncl.addWidget(name_lbl)

        # colored date based on age
        date_color = _date_color(updated_at)
        date_lbl = QLabel(updated_at or "")
        date_lbl.setFont(pixel_font(14))
        date_lbl.setStyleSheet(f"color:rgb({date_color.red()},{date_color.green()},{date_color.blue()});")
        date_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        ncl.addWidget(date_lbl)

        name_col.setMinimumWidth(80)
        lay.addWidget(name_col, 1)

        # last price column
        lp_lbl = QLabel(_fmt_price(last_price))
        lp_lbl.setFont(app_font(42))
        lp_lbl.setStyleSheet("color:rgb(180,220,180);")
        lp_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lp_lbl.setFixedWidth(_COL_PRICE)
        lp_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(lp_lbl)

        # median 7d column
        med_lbl = QLabel(_fmt_price(median_7d) if median_7d else "—")
        med_lbl.setFont(app_font(36))
        med_lbl.setStyleSheet("color:rgb(160,180,220);")
        med_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        med_lbl.setFixedWidth(_COL_PRICE)
        med_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(med_lbl)

        self._hovered = False
        self.setMouseTracking(True)

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, val):
        if self._selected != val:
            self._selected = val
            self.update()
            self.selectionChanged.emit()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        rad = 6.0
        if self._selected:
            p.setBrush(QColor(80, 200, 80, 15))
            p.setPen(QPen(QColor(80, 200, 80), 2))
            p.drawRoundedRect(r, rad, rad)
        elif self._hovered:
            p.setBrush(QColor(255, 255, 255, 8))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r, rad, rad)
        p.end()

    def enterEvent(self, ev):
        self._hovered = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hovered = False
        self.update()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            # don't toggle selection if clicking on the star
            child = self.childAt(ev.pos())
            if isinstance(child, _StarWidget):
                super().mousePressEvent(ev)
                return
            self.selected = not self._selected
            ev.accept()
        else:
            super().mousePressEvent(ev)


# ══════════════════════════════════════════════════════════════
#  MarketplaceWindow — separate resizable window for items list
# ══════════════════════════════════════════════════════════════


_SORT_HDR_CSS = """
    QPushButton {{
        background: transparent; color: {color};
        border: none; padding: 0;
    }}
    QPushButton:hover {{ color: rgb(255,255,255); }}
"""

_SORT_COLS = [
    ("Название",  1),   # name
    ("Посл.",     3),   # last price
    ("Медиана",   4),   # median 7d
]


class MarketplaceWindow(QWidget):
    def __init__(self, state, refresh_fn):
        super().__init__()
        self._state = state
        self._refresh_fn = refresh_fn   # callable: (server, cat_slug|None) -> items list
        self._drag_pos = None
        self._all_selected = False
        self._items_data = []
        self._filtered_data = []
        self._sort_col = 1       # default: sort by name
        self._sort_asc = True
        self._favorites = _load_favorites()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(700, 500)
        self.resize(900, 700)

        central = QWidget()
        central.setObjectName("mp_c")
        central.setStyleSheet("#mp_c{background:rgba(28,28,32,230); border-radius:5px;}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(central)

        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 5)
        main_lay.setSpacing(0)

        # ── title bar ──
        bar = QWidget()
        bar.setStyleSheet("background:transparent;")
        bs = 32
        bar.setFixedHeight(bs + 8)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(10, 4, 6, 0)
        bar_lay.setSpacing(4)

        title = QLabel("Предметы")
        title.setFont(app_font(28))
        title.setStyleSheet("color:rgb(200,200,200);")
        bar_lay.addWidget(title)

        # update button (sync from server)
        self._update_btn = QPushButton("Обновить")
        self._update_btn.setCursor(Qt.PointingHandCursor)
        self._update_btn.setFont(app_font(18))
        self._update_btn.setStyleSheet(_button_style())
        self._update_btn.setFixedHeight(bs)
        self._update_btn.clicked.connect(self._start_update)
        bar_lay.addWidget(self._update_btn)

        # scan button (OCR prices in-game)
        self._scan_btn = QPushButton("Сканировать")
        self._scan_btn.setCursor(Qt.PointingHandCursor)
        self._scan_btn.setFont(app_font(18))
        self._scan_btn.setStyleSheet(_button_style())
        self._scan_btn.setFixedHeight(bs)
        self._scan_btn.clicked.connect(self._start_scan)
        bar_lay.addWidget(self._scan_btn)

        bar_lay.addStretch()

        for icon, slot in [("minimize", self.showMinimized), ("close", self.close)]:
            b = TitleButton(icon)
            b.setFixedSize(bs, bs)
            b.clicked.connect(slot)
            bar_lay.addWidget(b)
        main_lay.addWidget(bar)

        # ── progress bar (hidden by default) ──
        self._progress_bar = MarketplaceProgressWidget()
        self._progress_bar.hide()
        main_lay.addWidget(self._progress_bar)

        # ── filters row: server | category | select all ──
        filt_row = QWidget()
        fl = QHBoxLayout(filt_row)
        fl.setContentsMargins(5, 3, 5, 3)
        fl.setSpacing(4)

        self._mp_server = _CenteredCombo()
        self._mp_server.addItems(MP_SERVERS)
        self._mp_server.setStyleSheet(_combo_style())
        self._mp_server.setFixedHeight(40)
        fl.addWidget(self._mp_server, 1)

        self._mp_category = _CenteredCombo()
        # index 0 = "Все", index 1 = "★ Избранное", then real categories
        self._mp_category.addItem(MP_CATEGORIES[0][1])  # "Все"
        self._mp_category.addItem("\u2605 Избранное")
        for _slug, ru in MP_CATEGORIES[1:]:
            self._mp_category.addItem(ru)
        self._mp_category.setStyleSheet(_combo_style())
        self._mp_category.setFixedHeight(40)
        fl.addWidget(self._mp_category, 1)

        # restore saved selection (before connecting signals)
        cfg = mp_db.load_config()
        si = cfg.get("mp_server", 0)
        if 0 <= si < self._mp_server.count():
            self._mp_server.setCurrentIndex(si)
        ci = cfg.get("mp_category", 0)
        if 0 <= ci < self._mp_category.count():
            self._mp_category.setCurrentIndex(ci)

        self._mp_server.currentIndexChanged.connect(self._on_filter_changed)
        self._mp_category.currentIndexChanged.connect(self._on_filter_changed)

        self._select_btn = QPushButton("Выбрать все")
        self._select_btn.setCursor(Qt.PointingHandCursor)
        self._select_btn.setStyleSheet(_button_style())
        self._select_btn.setFixedHeight(40)
        self._select_btn.clicked.connect(self._toggle_select_all)
        fl.addWidget(self._select_btn, 1)

        main_lay.addWidget(filt_row)

        # ── search row ──
        search_row = QWidget()
        sl = QHBoxLayout(search_row)
        sl.setContentsMargins(5, 0, 5, 3)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Поиск по названию...")
        self._search_input.setStyleSheet(_input_style())
        self._search_input.setFixedHeight(40)
        self._search_input.textChanged.connect(self._on_search_changed)
        sl.addWidget(self._search_input)
        main_lay.addWidget(search_row)

        # ── sort header ──
        hdr = QWidget()
        hdr.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8 + _COL_IMG + 12, 0, 8, 0)
        hl.setSpacing(8)
        self._sort_arrows = []
        _arrow_w = 18
        colors = {1: "rgb(200,200,200)", 3: "rgb(180,220,180)", 4: "rgb(160,180,220)"}
        for i, (label, col_idx) in enumerate(_SORT_COLS):
            clr = colors.get(col_idx, "rgb(200,200,200)")
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFont(app_font(20))
            btn.setStyleSheet(_SORT_HDR_CSS.format(color=clr))
            btn.clicked.connect(lambda _, ci=col_idx: self._on_sort(ci))
            arrow_lbl = QLabel("")
            arrow_lbl.setFont(app_font(16))
            arrow_lbl.setStyleSheet(f"color:{clr};")
            arrow_lbl.setFixedWidth(_arrow_w)
            arrow_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            if i == 0:
                hl.addWidget(btn, 1)
                hl.addWidget(arrow_lbl)
            else:
                btn.setFixedWidth(_COL_PRICE - _arrow_w)
                hl.addWidget(btn)
                hl.addWidget(arrow_lbl)
            self._sort_arrows.append((arrow_lbl, col_idx))
        hdr.setFixedHeight(30)
        main_lay.addWidget(hdr)

        # ── scroll area ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(_SCROLL_CSS)

        self._list = QWidget()
        self._list.setObjectName("mp_list")
        self._list_lay = QVBoxLayout(self._list)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(2)
        self._list_lay.addStretch()
        self._scroll.setWidget(self._list)
        main_lay.addWidget(self._scroll, 1)

        self._nam = QNetworkAccessManager(self)
        self._loader = _ThumbLoader(self._nam)

        # progress polling timer (for update button label)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_progress)

    def _start_update(self):
        s = self._state
        if s.marketplace_parsing:
            return
        loop = s.loop
        if not loop:
            return

        # Sync from server if authenticated, fallback to wiki scrape
        if s.api_client and s.is_authenticated:
            async def _sync():
                from modules.marketplace.sync import sync_items
                s.marketplace_parsing = True
                s.marketplace_done = 0
                s.marketplace_total = 1
                try:
                    server = self._mp_server.currentText()
                    cat_idx = self._mp_category.currentIndex()
                    cat_slug = None
                    if cat_idx > 1:
                        from modules.marketplace.parser import CATEGORIES as MP_CATEGORIES
                        real_idx = cat_idx - 1
                        cat_slug = MP_CATEGORIES[real_idx][0] if real_idx > 0 else None
                    await sync_items(s.api_client, server, cat_slug)
                    s.marketplace_done = 1
                except Exception:
                    s.marketplace_error = "Sync failed"
                finally:
                    s.marketplace_parsing = False
            asyncio.run_coroutine_threadsafe(_sync(), loop)
        else:
            selected = self._get_selected_ids()
            if selected:
                from modules.marketplace.parser import parse_selected
                asyncio.run_coroutine_threadsafe(parse_selected(s, selected), loop)
            else:
                from modules.marketplace.parser import parse_all
                asyncio.run_coroutine_threadsafe(parse_all(s), loop)

        self._update_btn.setEnabled(False)
        self._update_btn.setText("")
        self._progress_bar.set_progress(0, 0, 0, 0)
        self._progress_bar.show()
        self._poll_timer.start(500)

    def _start_scan(self):
        """Start price scan automation for selected items."""
        s = self._state
        if s.scan_active:
            # Stop scan
            s.scan_active = False
            self._scan_btn.setText("Сканировать")
            return
        selected = self._get_selected_ids()
        if not selected:
            return
        # Get names for selected items
        scan_items = []
        for i in range(self._list_lay.count()):
            w = self._list_lay.itemAt(i).widget()
            if isinstance(w, ItemRowWidget) and w.selected:
                name = w.data[1] if len(w.data) > 1 else ""
                scan_items.append((w.item_id, name))
        if not scan_items:
            return
        s.scan_items = scan_items
        s.scan_active = True
        self._scan_btn.setText("Стоп")

    def _poll_progress(self):
        s = self._state
        if s.marketplace_parsing:
            total = max(s.marketplace_total, 1)
            progress = s.marketplace_done / total
            self._progress_bar.set_progress(
                progress, s.marketplace_done, total, s.marketplace_start_time)
        else:
            self._poll_timer.stop()
            self._progress_bar.hide()
            self._update_btn.setText("Обновить")
            self._update_btn.setEnabled(True)
            self.refresh_data()

    def _toggle_select_all(self):
        self._all_selected = not self._all_selected
        self._select_btn.setText("Отменить все" if self._all_selected else "Выбрать все")
        for i in range(self._list_lay.count()):
            w = self._list_lay.itemAt(i).widget()
            if isinstance(w, ItemRowWidget):
                w.selected = self._all_selected

    def _get_selected_ids(self):
        ids = []
        for i in range(self._list_lay.count()):
            w = self._list_lay.itemAt(i).widget()
            if isinstance(w, ItemRowWidget) and w.selected:
                ids.append(w.item_id)
        return ids

    def _on_sort(self, col_idx):
        if self._sort_col == col_idx:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col_idx
            self._sort_asc = col_idx == 1
        self._update_sort_labels()
        self._rebuild_list()

    def _update_sort_labels(self):
        arrow = "\u25b2" if self._sort_asc else "\u25bc"
        for lbl, col_idx in self._sort_arrows:
            lbl.setText(arrow if col_idx == self._sort_col else "")

    def _on_favorite_changed(self, item_id, is_fav):
        if is_fav:
            self._favorites.add(item_id)
        else:
            self._favorites.discard(item_id)
        _save_favorites(self._favorites)
        # if viewing favorites tab, rebuild immediately
        if self._mp_category.currentIndex() == 1:
            self._rebuild_list()

    def _apply_filter(self):
        data = self._items_data
        # favorites filter (category index 1)
        if self._mp_category.currentIndex() == 1:
            data = [r for r in data if r[0] in self._favorites]
        query = self._search_input.text().strip().lower()
        if query:
            data = [r for r in data if query in (r[1] or "").lower()]
        self._filtered_data = data

    def _rebuild_list(self):
        self._apply_filter()
        data = list(self._filtered_data)
        ci = self._sort_col
        if ci == 1:
            data.sort(key=lambda r: (r[ci] or "").lower(), reverse=not self._sort_asc)
        else:
            data.sort(key=lambda r: r[ci], reverse=not self._sort_asc)
        self._fill_list(data)

    def _fill_list(self, items):
        self._loader.cancel_all()
        layout = self._list_lay
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        for row in items:
            w = ItemRowWidget(row, self._loader, self._favorites)
            w.favoriteChanged.connect(self._on_favorite_changed)
            layout.addWidget(w)
        layout.addStretch()
        self._all_selected = False
        self._select_btn.setText("Выбрать все")

    def _on_filter_changed(self):
        cfg = mp_db.load_config()
        cfg["mp_server"] = self._mp_server.currentIndex()
        cfg["mp_category"] = self._mp_category.currentIndex()
        mp_db.save_config(cfg)
        self.refresh_data()

    def _on_search_changed(self):
        self._rebuild_list()

    def refresh_data(self):
        self._favorites = _load_favorites()
        server = self._mp_server.currentText()
        cat_idx = self._mp_category.currentIndex()
        # index 0 = All, 1 = Favorites, 2+ = real categories (shifted by 1)
        if cat_idx <= 1:
            cat_slug = None  # All or Favorites — load all, filter later
        else:
            real_idx = cat_idx - 1  # offset for inserted "Избранное"
            cat_slug = MP_CATEGORIES[real_idx][0] if real_idx > 0 else None

        # Try cached price data first (from server sync), fallback to old format
        try:
            from modules.marketplace.sync import get_cached_items_with_prices
            items = get_cached_items_with_prices(server, cat_slug)
            if not items:
                items = self._refresh_fn(server, cat_slug)
        except Exception:
            items = self._refresh_fn(server, cat_slug)

        self._items_data = items
        self._update_sort_labels()
        self._rebuild_list()

    def populate(self, items):
        self._items_data = items
        self._update_sort_labels()
        self._rebuild_list()

    # ── dragging ──
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_pos = ev.globalPos() - self.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag_pos and ev.buttons() == Qt.LeftButton:
            self.move(ev.globalPos() - self._drag_pos)
            ev.accept()

    def mouseReleaseEvent(self, _ev):
        self._drag_pos = None


# ══════════════════════════════════════════════════════════════
#  SellItemRowWidget — thumbnail + name + quantity, click-to-select
# ══════════════════════════════════════════════════════════════


class SellItemRowWidget(QWidget):
    selectionChanged = pyqtSignal()

    def __init__(self, item_id, name, quantity, loader: _ThumbLoader, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.name = name
        self.quantity = quantity
        self._selected = True
        self._hovered = False

        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        # thumbnail
        self._thumb = QLabel()
        self._thumb.setFixedSize(_THUMB_SZ, _THUMB_SZ)
        self._thumb.setAlignment(Qt.AlignCenter)
        self._thumb.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._thumb)

        loader.request(item_id, self._thumb)

        # name
        name_lbl = QLabel(name or "")
        name_lbl.setFont(app_font(32))
        name_lbl.setStyleSheet("color:rgb(200,200,200);")
        name_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(name_lbl, 1)

        # quantity
        qty_lbl = QLabel(f"{quantity} шт." if quantity else "")
        qty_lbl.setFont(app_font(32))
        qty_lbl.setStyleSheet("color:rgb(100,160,255);")
        qty_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        qty_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(qty_lbl)

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, val):
        if self._selected != val:
            self._selected = val
            self.update()
            self.selectionChanged.emit()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        rad = 6.0
        if self._selected:
            p.setBrush(QColor(80, 200, 80, 15))
            p.setPen(QPen(QColor(80, 200, 80), 2))
            p.drawRoundedRect(r, rad, rad)
        elif self._hovered:
            p.setBrush(QColor(255, 255, 255, 8))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r, rad, rad)
        p.end()

    def enterEvent(self, ev):
        self._hovered = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hovered = False
        self.update()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.selected = not self._selected
            ev.accept()
        else:
            super().mousePressEvent(ev)


# ══════════════════════════════════════════════════════════════
#  SellWindow — item selection for selling
# ══════════════════════════════════════════════════════════════


class _SellDetectThread(QObject):
    """Runs OCR detection in a background thread, emits items one by one."""
    item_found = pyqtSignal(int, str, int)   # item_id, name, qty
    finished = pyqtSignal()

    def __init__(self, frame, db_items):
        super().__init__()
        self._frame = frame
        self._db_items = db_items

    def run(self):
        from modules.sell.detector import detect_items
        detect_items(self._frame, self._db_items, callback=self._on_item)
        self.finished.emit()

    def _on_item(self, iid, name, qty):
        self.item_found.emit(iid, name, qty)


class SellWindow(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self._state = state
        self._drag_pos = None
        self._all_selected = True
        self._detect_thread = None
        self._detect_worker = None
        self._running = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(750, 600)

        central = QWidget()
        central.setObjectName("sell_c")
        central.setStyleSheet("#sell_c{background:rgba(28,28,32,230); border-radius:5px;}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(central)

        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 5)
        main_lay.setSpacing(0)

        # ── title bar ──
        bar = QWidget()
        bar.setStyleSheet("background:transparent;")
        bs = 32
        bar.setFixedHeight(bs + 8)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(10, 4, 6, 0)
        bar_lay.setSpacing(4)

        self._title = QLabel("\u041f\u0440\u043e\u0434\u0430\u0436\u0430")
        self._title.setFont(app_font(28))
        self._title.setStyleSheet("color:rgb(200,200,200);")
        bar_lay.addWidget(self._title)

        bar_lay.addStretch()

        for icon, slot in [("minimize", self.showMinimized), ("close", self.close)]:
            b = TitleButton(icon)
            b.setFixedSize(bs, bs)
            b.clicked.connect(slot)
            bar_lay.addWidget(b)
        main_lay.addWidget(bar)

        # ── control row: [Выбрать все] [offset input] [Старт/Стоп] ──
        ctrl_row = QWidget()
        cl = QHBoxLayout(ctrl_row)
        cl.setContentsMargins(5, 3, 5, 3)
        cl.setSpacing(4)

        self._select_btn = QPushButton("\u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c \u0432\u0441\u0435")
        self._select_btn.setCursor(Qt.PointingHandCursor)
        self._select_btn.setStyleSheet(_button_style())
        self._select_btn.setFixedHeight(40)
        self._select_btn.clicked.connect(self._toggle_select_all)
        cl.addWidget(self._select_btn, 1)

        self._offset_input = QLineEdit("1")
        self._offset_input.setFixedWidth(80)
        self._offset_input.setFixedHeight(40)
        self._offset_input.setAlignment(Qt.AlignCenter)
        self._offset_input.setStyleSheet(_input_style())
        self._offset_input.setPlaceholderText("1")
        cl.addWidget(self._offset_input)

        self._start_btn = QPushButton("\u0421\u0442\u0430\u0440\u0442")
        self._start_btn.setCursor(Qt.PointingHandCursor)
        self._start_btn.setStyleSheet(_button_style())
        self._start_btn.setFixedHeight(40)
        self._start_btn.clicked.connect(self._toggle_sell)
        cl.addWidget(self._start_btn, 1)

        main_lay.addWidget(ctrl_row)

        # ── scroll area ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(_SCROLL_CSS)

        self._list = QWidget()
        self._list.setObjectName("mp_list")
        self._list_lay = QVBoxLayout(self._list)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(2)
        self._list_lay.addStretch()
        self._scroll.setWidget(self._list)
        main_lay.addWidget(self._scroll, 1)

        self._nam = QNetworkAccessManager(self)
        self._loader = _ThumbLoader(self._nam)
        self._item_count = 0

        # ── poll timer for sell step updates from asyncio loop ──
        self._sell_poll = QTimer(self)
        self._sell_poll.timeout.connect(self._poll_sell_step)

    def start_detection(self, frame, db_items):
        """Start OCR detection in background thread."""
        from PyQt5.QtCore import QThread
        self._title.setText("\u041f\u0440\u043e\u0434\u0430\u0436\u0430 \u2014 \u0441\u043a\u0430\u043d...")
        self._detect_thread = QThread()
        self._detect_worker = _SellDetectThread(frame, db_items)
        self._detect_worker.moveToThread(self._detect_thread)
        self._detect_thread.started.connect(self._detect_worker.run)
        self._detect_worker.item_found.connect(self._add_item)
        self._detect_worker.finished.connect(self._on_detect_done)
        self._detect_thread.start()

    def _add_item(self, item_id, name, qty):
        w = SellItemRowWidget(item_id, name, qty, self._loader)
        self._list_lay.insertWidget(self._list_lay.count() - 1, w)
        self._item_count += 1
        self._title.setText(f"\u041f\u0440\u043e\u0434\u0430\u0436\u0430 \u2014 \u0441\u043a\u0430\u043d... ({self._item_count})")

    def _on_detect_done(self):
        self._title.setText(f"\u041f\u0440\u043e\u0434\u0430\u0436\u0430 ({self._item_count})")
        if self._detect_thread:
            self._detect_thread.quit()
            self._detect_thread.wait()

    def _toggle_select_all(self):
        self._all_selected = not self._all_selected
        self._select_btn.setText(
            "\u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c \u0432\u0441\u0435" if self._all_selected
            else "\u0412\u044b\u0431\u0440\u0430\u0442\u044c \u0432\u0441\u0435"
        )
        for i in range(self._list_lay.count()):
            w = self._list_lay.itemAt(i).widget()
            if isinstance(w, SellItemRowWidget):
                w.selected = self._all_selected

    def _get_selected(self):
        result = []
        for i in range(self._list_lay.count()):
            w = self._list_lay.itemAt(i).widget()
            if isinstance(w, SellItemRowWidget) and w.selected:
                result.append((w.item_id, w.name, w.quantity))
        return result

    def _toggle_sell(self):
        s = self._state
        if self._running:
            # stop — asyncio loop checks sell_active
            s.sell_active = False
        else:
            selected = self._get_selected()
            if not selected:
                return
            offset_text = self._offset_input.text().strip()
            offset = int(offset_text) if offset_text.isdigit() else 1

            # set state for asyncio sell_bot_loop to pick up
            s.sell_items = selected
            s.sell_offset = offset
            s.sell_step = ""
            s.sell_active = True

            self._running = True
            self._start_btn.setText("\u0421\u0442\u043e\u043f")
            self._select_btn.setEnabled(False)
            self._offset_input.setEnabled(False)
            self._sell_poll.start(200)

    def _poll_sell_step(self):
        """Poll state.sell_step written by asyncio sell loop."""
        s = self._state
        step = s.sell_step
        if step == "done":
            # finished
            self._running = False
            self._start_btn.setText("\u0421\u0442\u0430\u0440\u0442")
            self._select_btn.setEnabled(True)
            self._offset_input.setEnabled(True)
            self._title.setText("\u041f\u0440\u043e\u0434\u0430\u0436\u0430 \u2014 \u0433\u043e\u0442\u043e\u0432\u043e")
            self._sell_poll.stop()
            s.sell_step = ""
        elif not s.sell_active and self._running:
            # stopped by user
            self._running = False
            self._start_btn.setText("\u0421\u0442\u0430\u0440\u0442")
            self._select_btn.setEnabled(True)
            self._offset_input.setEnabled(True)
            self._title.setText(f"\u041f\u0440\u043e\u0434\u0430\u0436\u0430 ({self._item_count})")
            self._sell_poll.stop()
        elif step:
            self._title.setText(f"\u041f\u0440\u043e\u0434\u0430\u0436\u0430 \u2014 {step}")

    # ── dragging ──
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_pos = ev.globalPos() - self.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag_pos and ev.buttons() == Qt.LeftButton:
            self.move(ev.globalPos() - self._drag_pos)
            ev.accept()

    def mouseReleaseEvent(self, _ev):
        self._drag_pos = None

    def closeEvent(self, ev):
        self._state.sell_active = False
        self._sell_poll.stop()
        if self._detect_thread and self._detect_thread.isRunning():
            self._detect_thread.quit()
            self._detect_thread.wait()
        super().closeEvent(ev)


# ══════════════════════════════════════════════════════════════
#  MainWindow — square dark panel, top-right corner
# ══════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    # page_index → back target (int = page, str = method name)
    _BACK = {1: "_close_queue_page", 2: 0, 3: 2, 4: 0, 5: 4, 6: 0}

    def __init__(self, state):
        super().__init__()
        self._state = state
        _load_fonts()

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        scr = QApplication.primaryScreen().geometry()
        self._h = scr.height() // 5          # reference for element sizing
        self._w = self._h * 4 // 5
        btn_row = 27 + 10 + 5                # font + padding + spacing
        self.setFixedSize(self._w, self._h - btn_row * 3)
        self.move(scr.width() - self._w, 0)

        central = QWidget()
        central.setObjectName("c")
        central.setStyleSheet("#c{background:rgba(28,28,32,230);}")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_title_bar())

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)
        self._stack.addWidget(self._build_menu_page())    # 0
        self._stack.addWidget(self._build_queue_page())   # 1
        self._stack.addWidget(self._build_helper_page())  # 2
        self._stack.addWidget(self._build_stash_page())   # 3
        self._stack.addWidget(self._build_bots_page())    # 4
        self._stack.addWidget(self._build_fishing_page()) # 5
        self._stack.addWidget(self._build_accounts_page()) # 6

        self._overlay = OverlayWindow(state)

        self._mp_window = MarketplaceWindow(state, self._fetch_marketplace_items)
        self._sell_window = None

        self._fish_timer = QTimer(self)
        self._fish_timer.timeout.connect(self._on_fish_tick)

        self._sell_sync_timer = QTimer(self)
        self._sell_sync_timer.timeout.connect(self._on_sell_sync)
        self._sell_syncing = False

        self._game_found = False
        self._tg_color = None
        self._drag_pos = None

        self._update_game_status()

        # global click sound
        _init_click_sound()
        self._click_filter = _ClickSoundFilter(self)
        QApplication.instance().installEventFilter(self._click_filter)

        t = QTimer(self)
        t.timeout.connect(self._on_tick)
        t.start(1000)

    # ── Title bar ──

    def _build_title_bar(self):
        bar = QWidget()
        bar.setStyleSheet("background:transparent;")
        bs = max(self._h // 12, 12)
        bar.setFixedHeight(bs + 4)
        side_w = bs * 2 + 4

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(4, 2, 4, 0)
        lay.setSpacing(0)

        # left
        left = QWidget()
        left.setFixedWidth(side_w)
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        self._btn_back = QPushButton("<")
        self._btn_back.setCursor(Qt.PointingHandCursor)
        self._btn_back.setFixedSize(bs, bs)
        self._btn_back.setStyleSheet(_button_style())
        self._btn_back.clicked.connect(self._go_back)
        self._btn_back.hide()
        ll.addWidget(self._btn_back)
        ll.addStretch()
        lay.addWidget(left)

        lay.addStretch()

        # center icons
        self.game_icon = IconWidget("gta5")
        self.game_icon.setFixedSize(bs, bs)
        self.game_icon.set_color(COLOR_RED)
        lay.addWidget(self.game_icon)

        self.tg_icon = IconWidget("telegram")
        self.tg_icon.setFixedSize(bs, bs)
        self.tg_icon.set_color(COLOR_RED)
        self.tg_icon.setCursor(Qt.PointingHandCursor)
        self.tg_icon.mousePressEvent = lambda _: self._toggle_telegram()
        lay.addWidget(self.tg_icon)

        lay.addStretch()

        # right
        right = QWidget()
        right.setFixedWidth(side_w)
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)
        rl.addStretch()
        for icon, slot in [("minimize", self.showMinimized), ("close", self.close)]:
            b = TitleButton(icon)
            b.setFixedSize(bs, bs)
            b.clicked.connect(slot)
            rl.addWidget(b)
        lay.addWidget(right)

        return bar

    # ── Navigation ──

    def _go_to(self, idx):
        self._stack.setCurrentIndex(idx)
        self._btn_back.setVisible(idx != 0)

    def _go_back(self):
        target = self._BACK.get(self._stack.currentIndex())
        if target is None:
            return
        if isinstance(target, str):
            getattr(self, target)()
        else:
            self._go_to(target)

    # ── Pages ──

    def _build_menu_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)
        for text, slot in [("Хелпер",  lambda: self._go_to(2)),
                           ("Боты",    lambda: self._go_to(4)),
                           ("Счеты",   lambda: self._go_to(6))]:
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(_button_style())
            b.clicked.connect(slot)
            lay.addWidget(b)
        lay.addStretch()
        return page

    def _build_queue_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)

        self._queue_label = QLabel("\u2014")
        self._queue_label.setAlignment(Qt.AlignCenter)
        self._queue_label.setStyleSheet("color:rgb(220,220,220);")
        self._queue_label.setFont(app_font(self._h // 3))
        lay.addWidget(self._queue_label, 1)

        self._queue_eta = QueueETAWidget()
        lay.addWidget(self._queue_eta)

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)

        self._search_toggle = ToggleSwitch(checked=False)
        self._search_toggle.setFixedSize(48, 26)
        self._search_toggle.toggled.connect(self._on_search_toggle)
        rl.addWidget(self._search_toggle)

        lbl = QLabel("Порог")
        lbl.setStyleSheet("color:rgb(180,180,180);")
        lbl.setFont(app_font(24))
        rl.addWidget(lbl)
        rl.addStretch()

        self._threshold_input = QLineEdit("30")
        self._threshold_input.setFixedWidth(65)
        self._threshold_input.setAlignment(Qt.AlignCenter)
        self._threshold_input.setStyleSheet(_input_style())
        self._threshold_input.textChanged.connect(self._on_threshold_changed)
        rl.addWidget(self._threshold_input)

        lay.addWidget(row)
        return page

    def _build_helper_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)
        for text, slot in [("Очередь", self._open_queue_page),
                           ("Тайники", lambda: self._go_to(3))]:
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(_button_style())
            b.clicked.connect(slot)
            lay.addWidget(b)
        lay.addStretch()
        return page

    def _build_stash_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        m = 7
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(m)
        self._stash_widgets = []
        for name, hours, om, dur in STASHES:
            w = StashTimerWidget(name, hours, om, dur)
            self._stash_widgets.append(w)
            lay.addWidget(w, 1)
        return page

    def _build_bots_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)
        b = QPushButton("Рыбалка")
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(_button_style())
        b.clicked.connect(lambda: self._go_to_gated(5, "fishing"))
        lay.addWidget(b)
        lay.addStretch()
        return page

    def _go_to_gated(self, page_idx, module_id):
        """Navigate to page if user has access, otherwise prompt subscription."""
        s = self._state
        if s.subscription_manager and not s.subscription_manager.has_access(module_id):
            import webbrowser
            webbrowser.open(f"https://t.me/MjPortBot?start=subscribe_{module_id}")
            return
        self._go_to(page_idx)

    def _build_fishing_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)

        self._fish_status = QLabel("Остановлен")
        self._fish_status.setAlignment(Qt.AlignCenter)
        self._fish_status.setFont(app_font(27))
        self._fish_status.setStyleSheet("color:rgb(200,200,200);")
        lay.addWidget(self._fish_status, 1)

        self._fish_btn = QPushButton("Старт")
        self._fish_btn.setCursor(Qt.PointingHandCursor)
        self._fish_btn.setStyleSheet(_button_style())
        self._fish_btn.clicked.connect(self._toggle_fishing)
        lay.addWidget(self._fish_btn)
        return page

    def _build_accounts_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)
        b = QPushButton("Предметы")
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(_button_style())
        b.clicked.connect(self._show_marketplace_window)
        lay.addWidget(b)
        b2 = QPushButton("Продать")
        b2.setCursor(Qt.PointingHandCursor)
        b2.setStyleSheet(_button_style())
        b2.clicked.connect(self._start_sell_gated)
        lay.addWidget(b2)
        lay.addStretch()
        return page

    # ── Marketplace ──

    def _show_marketplace_window(self):
        win = self._mp_window
        if win.isVisible():
            # focus / raise existing window
            win.setWindowState(win.windowState() & ~Qt.WindowMinimized)
            win.raise_()
            win.activateWindow()
        else:
            win.refresh_data()
            win.show()

    def _fetch_marketplace_items(self, server, cat_slug):
        try:
            mp_db.init_db()
            return mp_db.get_items_with_prices(server, cat_slug)
        except Exception:
            return []

    # ── Sell detection ──

    def _start_sell_gated(self):
        """Check subscription before starting sell."""
        s = self._state
        if s.subscription_manager and not s.subscription_manager.has_access("sell"):
            import webbrowser
            webbrowser.open("https://t.me/MjPortBot?start=subscribe_sell")
            return
        self._start_sell_detection()

    def _start_sell_detection(self):
        import logging
        log = logging.getLogger(__name__)
        s = self._state
        provider = s.frame_provider
        if provider is None:
            log.warning("Sell: frame_provider is None")
            return
        if not provider.running:
            provider.start()
        # wait for WGC to deliver first frame (up to 3s)
        import time
        frame = None
        for _ in range(30):
            frame = provider.get_image()
            if frame is not None:
                break
            time.sleep(0.1)
        if frame is None:
            log.warning("Sell: get_image() returned None (game not captured?)")
            return
        log.info("Sell: got frame %sx%s", frame.width, frame.height)
        from modules.marketplace.database import init_db, get_all_item_names
        init_db()
        db_items = get_all_item_names()
        log.info("Sell: %d items in DB", len(db_items))
        # open window immediately, detection runs in background
        if self._sell_window is not None:
            self._sell_window.close()
        self._sell_window = SellWindow(s)
        self._sell_window.show()
        self._sell_window.start_detection(frame, db_items)

    def _toggle_fishing(self):
        s = self._state
        # if countdown is running, treat as stop
        if hasattr(self, '_fish_countdown') and self._fish_countdown > 0:
            self._fish_countdown = 0
            self._fish_cd_timer.stop()
            self._fish_btn.setText("Старт")
            self._fish_status.setText("Остановлен")
            return
        if s.fishing_active:
            s.fishing_active = False
            self._fish_btn.setText("Старт")
            self._fish_status.setText("Остановлен")
            self._fish_timer.stop()
        else:
            # start 3s countdown
            self._fish_countdown = 3
            self._fish_btn.setText("Стоп")
            self._fish_status.setText("3")
            if not hasattr(self, '_fish_cd_timer'):
                self._fish_cd_timer = QTimer(self)
                self._fish_cd_timer.timeout.connect(self._on_fish_countdown)
            self._fish_cd_timer.start(1000)

    def _on_fish_countdown(self):
        self._fish_countdown -= 1
        if self._fish_countdown > 0:
            self._fish_status.setText(str(self._fish_countdown))
        else:
            self._fish_cd_timer.stop()
            self._state.fishing_active = True
            self._fish_status.setText("Заброс")
            self._fish_timer.start(33)

    def _on_fish_tick(self):
        s = self._state
        step = s.fishing_step
        if step in ("idle", "init", "cast"):
            self._fish_status.setText("Заброс")
        elif step == "strike":
            txt = "Подсечка (пузыри!)" if s.fishing_bubbles else "Подсечка"
            self._fish_status.setText(txt)
        elif step == "reel":
            d = s.fishing_camera_dir
            if d == "left":
                self._fish_status.setText("\u2190\nВытягивание")
            elif d == "right":
                self._fish_status.setText("\u2192\nВытягивание")
            else:
                self._fish_status.setText("Вытягивание")
        elif step == "take":
            remaining = s.fishing_take_pause - _time.monotonic()
            if remaining > 0:
                self._fish_status.setText(f"Пауза {remaining:.1f}с")
            else:
                self._fish_status.setText("Забрать")
        self._overlay.sync()

    # ── Callbacks ──

    def _toggle_telegram(self):
        if self._state.is_authenticated:
            # Already logged in — log out
            self._state.token_store.clear()
            self._state.is_authenticated = False
            self._state.user_info = None
        else:
            # Start auth flow — open browser
            self._start_auth_flow()

    def _start_auth_flow(self):
        """Open browser for Telegram auth via localhost callback."""
        import webbrowser
        from auth.login_server import LoginCallbackServer

        server = LoginCallbackServer()
        port = server.start()

        s = self._state
        redirect = f"http://127.0.0.1:{port}/callback"
        auth_url = f"{s.server_url}/auth/login-page?redirect={redirect}"
        webbrowser.open(auth_url)

        # Handle callback in background
        async def _wait_auth():
            data = await server.wait_for_callback(timeout=120)
            if data and s.api_client:
                # Convert callback params to auth request
                auth_data = {
                    "id": int(data.get("id", 0)),
                    "first_name": data.get("first_name"),
                    "last_name": data.get("last_name"),
                    "username": data.get("username"),
                    "photo_url": data.get("photo_url"),
                    "auth_date": int(data.get("auth_date", 0)),
                    "hash": data.get("hash", ""),
                }
                ok = await s.api_client.auth_telegram(auth_data)
                if ok:
                    me = await s.api_client.get_me()
                    if me:
                        s.user_info = me.get("user")
                        s.is_authenticated = True

        if s.loop:
            asyncio.run_coroutine_threadsafe(_wait_auth(), s.loop)

    def _parse_threshold(self, text):
        t = text.strip()
        return int(t) if t.isdigit() and int(t) > 0 else 0

    def _on_search_toggle(self, checked):
        if checked:
            self._state.notify_threshold = self._parse_threshold(self._threshold_input.text())
            self._threshold_input.setEnabled(False)
            self._state.queue_search_active = True
        else:
            self._state.queue_search_active = False
            self._threshold_input.setEnabled(True)

    def _on_threshold_changed(self, text):
        self._state.notify_threshold = self._parse_threshold(text)

    def _open_queue_page(self):
        self._state.queue_page_open = True
        self._go_to(1)

    def _close_queue_page(self):
        self._state.queue_page_open = False
        self._state.queue_search_active = False
        self._search_toggle.setChecked(False)
        self._threshold_input.setEnabled(True)
        self._go_to(2)

    # ── Tick (1 s) ──

    def _on_tick(self):
        self._update_game_status()
        self._update_tg_icon()
        pos = self._state.queue_position
        self._queue_label.setText(str(pos) if pos is not None else "\u2014")
        self._queue_eta.refresh(self._state)
        for w in self._stash_widgets:
            w.refresh()
        self._overlay.sync()
        # auto-start/stop sell overlay sync timer
        if self._state.sell_active and not self._sell_syncing:
            self._sell_sync_timer.start(200)
            self._sell_syncing = True
        elif not self._state.sell_active and self._sell_syncing:
            self._sell_sync_timer.stop()
            self._sell_syncing = False
            self._overlay.sync()  # final sync to clear sell rects

    def _on_sell_sync(self):
        self._overlay.sync()

    def _update_game_status(self):
        found = is_game_running()
        if found != self._game_found:
            self._game_found = found
            self.game_icon.set_color(COLOR_GREEN if found else COLOR_RED)

    def _update_tg_icon(self):
        s = self._state
        c = COLOR_GREEN if s.is_authenticated else COLOR_RED
        if c != self._tg_color:
            self._tg_color = c
            self.tg_icon.set_color(c)

    # ── Dragging ──

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_pos = ev.globalPos() - self.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag_pos and ev.buttons() == Qt.LeftButton:
            self.move(ev.globalPos() - self._drag_pos)
            ev.accept()

    def mouseReleaseEvent(self, _ev):
        self._drag_pos = None

    def closeEvent(self, ev):
        self._overlay.close()
        self._mp_window.close()
        if self._sell_window is not None:
            self._sell_window.close()
        super().closeEvent(ev)
