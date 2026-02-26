import os
import sys
import ctypes
import logging
import threading
import time as _time
from datetime import datetime, timezone, timedelta

import asyncio

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QApplication, QStackedWidget, QLineEdit,
)
from PyQt5.QtCore import (
    Qt, QTimer, QRectF, QUrl, pyqtSignal, QObject, QEvent,
)
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QFont, QFontDatabase,
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

from core import is_game_running
from utils import resource_path
from ui.widgets import IconWidget, SpinningIconWidget, TitleButton, ToggleSwitch

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
    QPushButton, QLineEdit,
)


class _ClickSoundFilter(QObject):
    """App-wide event filter that plays click sound on interactive widgets."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if isinstance(obj, _CLICK_TYPES):
                play_click()
            elif type(obj).__name__ in ("ToggleSwitch", "TitleButton"):
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

        if show_queue or show_fish:
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
                    s.fishing_take_icon)
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
#  _FooterBar — footer with background progress bar
# ══════════════════════════════════════════════════════════════

class _FooterBar(QWidget):
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

        # background
        p.setPen(Qt.NoPen)
        p.setBrush(self._BG)
        p.drawRect(0, 0, w, h)

        # progress fill
        bw = int(w * self._progress)
        if bw > 0:
            p.setBrush(self._FILL)
            p.drawRect(0, 0, bw, h)

        # top border line
        p.setPen(QPen(self._BORDER_TOP, 1))
        p.drawLine(0, 0, w, 0)

        p.end()


# ══════════════════════════════════════════════════════════════
#  MainWindow — square dark panel, top-right corner
# ══════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    # signals for thread→GUI communication (update checker)
    _sig_update_progress = pyqtSignal(float, str)  # (progress, status_text)
    _sig_update_result = pyqtSignal(str)            # "ok" | "apply:path" | "no_server" | "error"

    # page_index → back target (int = page, str = method name)
    _BACK = {1: "_close_queue_page", 2: 0, 3: 2, 4: 0, 5: 4}

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
        footer_h = 22
        self.setFixedSize(self._w, self._h - btn_row * 3 + footer_h)
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

        # ── Footer ──
        root.addWidget(self._build_footer())

        # ── UI lock until update check completes ──
        self._ui_locked = True
        self._stack.setEnabled(False)

        self._overlay = OverlayWindow(state)

        self._fish_timer = QTimer(self)
        self._fish_timer.timeout.connect(self._on_fish_tick)

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

        # Connect update signals (thread-safe GUI updates)
        self._sig_update_progress.connect(self._on_update_progress)
        self._sig_update_result.connect(self._on_update_result)

        # Start update check in background thread
        self._start_update_check()

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

    # ── Footer ──

    def _build_footer(self):
        self._footer = _FooterBar()

        self._update_icon = SpinningIconWidget("update")
        self._update_icon.setFixedSize(16, 16)
        self._update_icon.set_color(COLOR_YELLOW)

        lay = QHBoxLayout(self._footer)
        lay.setContentsMargins(7, 0, 5, 0)
        lay.setSpacing(0)

        from version import __version__
        ver = QLabel(f"v{__version__}")
        ver.setFont(pixel_font(14))
        ver.setStyleSheet("color: rgba(180,180,180,120); background: transparent; border: none;")
        lay.addWidget(ver)

        lay.addStretch()

        self._update_status = QLabel("")
        self._update_status.setFont(pixel_font(12))
        self._update_status.setStyleSheet("color: rgba(180,180,180,100); background: transparent; border: none;")
        lay.addWidget(self._update_status)

        lay.addSpacing(4)
        lay.addWidget(self._update_icon)

        return self._footer

    # ── Update check ──

    def _start_update_check(self):
        self._update_icon.set_color(COLOR_YELLOW)
        self._update_icon.start_spin()
        self._footer.set_progress(0.0)
        self._update_status.setText("проверка...")
        t = threading.Thread(target=self._update_worker, daemon=True)
        t.start()

    def _update_worker(self):
        """Background thread: check version, download if needed. All sync."""
        from updater import check_update_sync, download_update_sync
        from core import SERVER_URL

        # 1. Check version
        try:
            info = check_update_sync(SERVER_URL)
        except Exception:
            self._sig_update_result.emit("no_server")
            return

        if info is None:
            self._sig_update_progress.emit(1.0, "актуально")
            self._sig_update_result.emit("ok")
            return

        url = info.get("download_url", "")
        if not url:
            self._sig_update_progress.emit(1.0, "актуально")
            self._sig_update_result.emit("ok")
            return

        if not getattr(sys, 'frozen', False):
            self._sig_update_progress.emit(1.0, "dev mode")
            self._sig_update_result.emit("ok")
            return

        # 2. Download
        version = info.get("version", "?")
        self._sig_update_progress.emit(0.0, f"загрузка {version}...")
        dest = os.path.join(os.path.dirname(sys.executable), "Mary Jane_new.exe")

        def on_progress(pct):
            p = int(pct * 100)
            self._sig_update_progress.emit(pct, f"{p}%")

        ok = download_update_sync(url, dest, on_progress)
        if ok:
            self._sig_update_progress.emit(1.0, "перезапуск...")
            self._sig_update_result.emit("apply:" + dest)
        else:
            self._sig_update_result.emit("error")

    # ── Update slots (run on GUI thread via signal) ──

    def _on_update_progress(self, value: float, text: str):
        self._footer.set_progress(value)
        self._update_status.setText(text)

    def _on_update_result(self, result: str):
        self._update_icon.stop_spin()
        if result == "ok":
            self._update_icon.set_color(COLOR_GREEN)
            self._footer.set_progress(1.0)
            self._unlock_ui()
        elif result.startswith("apply:"):
            from updater import apply_update
            apply_update(result[6:])
        elif result == "no_server":
            self._update_icon.set_color(COLOR_RED)
            self._footer.set_progress(0.0)
            self._update_status.setText("нет связи")
            QTimer.singleShot(10_000, self._start_update_check)
        else:
            self._update_icon.set_color(COLOR_RED)
            self._footer.set_progress(0.0)
            self._update_status.setText("ошибка")
            QTimer.singleShot(10_000, self._start_update_check)

    def _unlock_ui(self):
        self._ui_locked = False
        self._stack.setEnabled(True)

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
        for text, slot in [("Хелперы", lambda: self._go_to(2)),
                           ("Боты",    lambda: self._go_to(4))]:
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

        self._gated_buttons = []  # [(QPushButton, QLabel, module_id), ...]

        for text, page_idx, module_id in [("Рыбалка", 5, "fishing")]:
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(_button_style())
            b.clicked.connect(lambda _=False, p=page_idx, m=module_id: self._go_to_gated(p, m))

            # Small expiry label overlaid at the bottom of the button
            exp_label = QLabel(b)
            exp_label.setAlignment(Qt.AlignCenter)
            exp_label.setStyleSheet(
                f"color: rgba(255,255,200,180); font-size: 11px;"
                f" font-family: '{_font_families.get('pixel', '')}';"
                f" background: transparent;"
            )
            exp_label.hide()

            self._gated_buttons.append((b, exp_label, module_id))
            lay.addWidget(b)

        lay.addStretch()
        return page

    def _update_gated_buttons(self):
        """Update yellow border and expiry text on paid module buttons."""
        sm = self._state.subscription_manager
        if not sm:
            return
        for btn, exp_label, module_id in self._gated_buttons:
            expires = sm.get_expires(module_id)
            if expires and sm.has_access(module_id):
                # Yellow border for active subscription
                ff = f"font-family: '{_font_families['app']}';" if _font_families.get("app") else ""
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: rgb(32,32,38); color: rgb(240,240,240);
                        border: 1px solid rgba(255,200,50,180); border-radius: 5px;
                        padding: 5px; font-size: 27px; {ff}
                    }}
                    QPushButton:hover {{ background: rgb(44,44,52); }}
                """)
                # Parse and format expiry date
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(expires)
                    exp_text = f"до {dt.strftime('%d.%m.%Y')}"
                except Exception:
                    exp_text = ""
                if exp_text:
                    exp_label.setText(exp_text)
                    # Position at bottom center of button
                    bw, bh = btn.width(), btn.height()
                    lw = bw
                    lh = 14
                    exp_label.setGeometry(0, bh - lh - 2, lw, lh)
                    exp_label.show()
                else:
                    exp_label.hide()
            else:
                btn.setStyleSheet(_button_style())
                exp_label.hide()

    def _go_to_gated(self, page_idx, module_id):
        """Navigate to page if user has access, otherwise request invoice via API."""
        s = self._state
        if s.subscription_manager and not s.subscription_manager.has_access(module_id):
            if not s.is_authenticated:
                self._start_auth_flow()
                return
            if s.api_client and s.loop:
                asyncio.run_coroutine_threadsafe(
                    s.api_client.request_subscription(module_id), s.loop,
                )
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
                        if s.subscription_manager:
                            await s.subscription_manager.refresh()

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
        self._update_gated_buttons()

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
        super().closeEvent(ev)
