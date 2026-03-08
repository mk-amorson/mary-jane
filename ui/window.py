"""MainWindow — the main application window."""

import os
import sys
import ctypes
import logging
import threading
import time as _time

import asyncio

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QApplication, QStackedWidget, QLineEdit, QSlider,
    QScrollArea,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from core import is_game_running, get_game_rect
from ui.styles import (
    load_fonts, app_font, pixel_font,
    COLOR_RED, COLOR_YELLOW, COLOR_GREEN,
    button_style, input_style,
    _font_families,
)
from ui.sounds import init_click_sound, play_click, ClickSoundFilter
from ui.widgets import IconWidget, SpinningIconWidget, TitleButton, ToggleSwitch
from ui.overlay import OverlayWindow
from ui.stash import STASHES, StashTimerWidget, StashFloatWindow
from ui.queue import QueueETAWidget
from ui.footer import FooterBar
from ui.items import ItemsWindow

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    _sig_update_progress = pyqtSignal(float, str)
    _sig_update_result = pyqtSignal(str)

    _BACK = {1: "_close_queue_page", 2: 0, 3: 2, 4: 0, 5: 4, 6: 0, 7: 2}

    def __init__(self, state):
        super().__init__()
        self._state = state
        load_fonts()

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        scr = QApplication.primaryScreen().geometry()
        self._h = scr.height() // 5
        self._w = self._h * 4 // 5
        btn_row = 27 + 10 + 5
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
        self._stack.addWidget(self._build_menu_page())      # 0
        self._stack.addWidget(self._build_queue_page())      # 1
        self._stack.addWidget(self._build_helper_page())     # 2
        self._stack.addWidget(self._build_stash_page())      # 3
        self._stack.addWidget(self._build_bots_page())       # 4
        self._stack.addWidget(self._build_fishing2_page())   # 5
        self._stack.addWidget(self._build_settings_page())   # 6
        self._stack.addWidget(self._build_markers_page())    # 7

        root.addWidget(self._build_footer())

        self._ui_locked = True
        self._stack.setEnabled(False)

        self._overlay = OverlayWindow(state)
        self._stash_float = StashFloatWindow()

        self._fish2_timer = QTimer(self)
        self._fish2_timer.timeout.connect(self._on_fish2_tick)

        self._game_found = False
        self._drag_pos = None

        self._update_game_status()

        init_click_sound()
        self._click_filter = ClickSoundFilter(self)
        QApplication.instance().installEventFilter(self._click_filter)

        t = QTimer(self)
        t.timeout.connect(self._on_tick)
        t.start(1000)

        self._markers_timer = QTimer(self)
        self._markers_timer.timeout.connect(self._update_markers)
        self._markers_timer.start(50)

        self._sig_update_progress.connect(self._on_update_progress)
        self._sig_update_result.connect(self._on_update_result)
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

        left = QWidget()
        left.setFixedWidth(side_w)
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        self._btn_back = QPushButton("<")
        self._btn_back.setCursor(Qt.PointingHandCursor)
        self._btn_back.setFixedSize(bs, bs)
        self._btn_back.setStyleSheet(button_style())
        self._btn_back.clicked.connect(self._go_back)
        self._btn_back.hide()
        ll.addWidget(self._btn_back)
        ll.addStretch()
        lay.addWidget(left)

        lay.addStretch()

        self.game_icon = IconWidget("gta5")
        self.game_icon.setFixedSize(bs, bs)
        self.game_icon.set_color(COLOR_RED)
        self.game_icon.setCursor(Qt.PointingHandCursor)
        self.game_icon.mousePressEvent = lambda _: self._focus_game()
        lay.addWidget(self.game_icon)

        lay.addStretch()

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

        th = max(bs // 2, 8)
        tw = int(th * 2.6)
        self._title_toggle = ToggleSwitch(checked=False, parent=bar)
        self._title_toggle.setFixedSize(tw, th)
        self._title_toggle.hide()
        self._title_bar = bar
        self._title_bs = bs

        return bar

    # ── Footer ──

    def _build_footer(self):
        self._footer = FooterBar()

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
        from updater import check_update_sync, download_update_sync

        try:
            info = check_update_sync()
        except Exception:
            self._sig_update_result.emit("no_server")
            return

        if info is None:
            self._sig_update_progress.emit(1.0, "")
            self._sig_update_result.emit("ok")
            return

        url = info.get("download_url", "")
        if not url:
            self._sig_update_progress.emit(1.0, "")
            self._sig_update_result.emit("ok")
            return

        if not getattr(sys, 'frozen', False):
            self._sig_update_progress.emit(1.0, "dev mode")
            self._sig_update_result.emit("ok")
            return

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

    def _on_update_progress(self, value, text):
        self._footer.set_progress(value)
        self._update_status.setText(text)

    def _on_update_result(self, result):
        self._update_icon.stop_spin()
        if result == "ok":
            self._update_icon.icon_type = "check"
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
        prev = self._stack.currentIndex()
        self._stack.setCurrentIndex(idx)
        self._btn_back.setVisible(idx != 0)
        self._setup_title_toggle(idx)
        if idx == 7:
            self._state.markers_active = True
        elif prev == 7:
            self._state.markers_active = False

    def _go_back(self):
        target = self._BACK.get(self._stack.currentIndex())
        if target is None:
            return
        if isinstance(target, str):
            getattr(self, target)()
        else:
            self._go_to(target)

    _TOGGLE_PAGES = {1: "_on_queue_toggle", 3: "_on_stash_toggle"}

    def _setup_title_toggle(self, idx):
        tg = self._title_toggle
        try:
            tg.toggled.disconnect()
        except TypeError:
            pass
        handler = self._TOGGLE_PAGES.get(idx)
        if handler:
            tg.setChecked(self._state.queue_search_active if idx == 1
                          else getattr(self._state, 'stash_active', False))
            tg.toggled.connect(getattr(self, handler))
            tg.show()
            QTimer.singleShot(0, self._position_title_toggle)
        else:
            tg.hide()

    def _position_title_toggle(self):
        tg = self._title_toggle
        bar = self._title_bar
        back_right = self._btn_back.mapTo(bar, self._btn_back.rect().topRight()).x()
        icon_left = self.game_icon.mapTo(bar, self.game_icon.rect().topLeft()).x()
        cx = (back_right + icon_left) // 2
        cy = (bar.height() - tg.height()) // 2
        tg.move(cx - tg.width() // 2, cy)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._title_toggle.isVisible():
            self._position_title_toggle()

    # ── Pages ──

    def _build_menu_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)
        for text, slot in [("Хелперы",   lambda: self._go_to(2)),
                           ("Боты",      lambda: self._go_to(4)),
                           ("Настройки", lambda: self._go_to(6))]:
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(button_style())
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

        lbl = QLabel("Порог")
        lbl.setStyleSheet("color:rgb(180,180,180);")
        lbl.setFont(app_font(24))
        rl.addWidget(lbl)
        rl.addStretch()

        self._threshold_input = QLineEdit("30")
        self._threshold_input.setFixedWidth(65)
        self._threshold_input.setAlignment(Qt.AlignCenter)
        self._threshold_input.setStyleSheet(input_style())
        self._threshold_input.textChanged.connect(self._on_threshold_changed)
        rl.addWidget(self._threshold_input)

        lay.addWidget(row)
        return page

    def _build_helper_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        buttons = [
            ("Очередь", self._open_queue_page),
            ("Тайники", lambda: self._go_to(3)),
            ("Предметы", self._open_items_window),
            ("Координаты", lambda: self._go_to(7)),
        ]

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(7, 5, 7, 5)
        cl.setSpacing(5)
        for text, slot in buttons:
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(button_style())
            b.clicked.connect(slot)
            cl.addWidget(b)
        cl.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; }
            QScrollBar:vertical {
                background: rgb(28, 28, 32); width: 6px; border: none;
                margin: 2px 1px 2px 0;
            }
            QScrollBar::handle:vertical {
                background: rgb(60, 60, 68); border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """)

        lay.addWidget(scroll, 1)
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

    def _build_markers_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 8, 12, 5)
        lay.setSpacing(0)

        self._marker_labels = {}
        lbl_style = "color:rgb(200,200,200); background:transparent; border:none;"

        def make_group(keys, font_size=16):
            group = QWidget()
            gl = QVBoxLayout(group)
            gl.setContentsMargins(0, 4, 0, 4)
            gl.setSpacing(1)
            for key in keys:
                lbl = QLabel(f"{key}  \u2014")
                lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                lbl.setFont(pixel_font(font_size))
                lbl.setStyleSheet(lbl_style)
                self._marker_labels[key] = lbl
                gl.addWidget(lbl)
            return group

        # Player position
        lay.addWidget(make_group(["X", "Y", "Z"], 18))

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:rgba(200,200,200,30);")
        lay.addSpacing(4)
        lay.addWidget(sep)
        lay.addSpacing(4)

        # Body heading
        lay.addWidget(make_group(["Heading"], 14))

        lay.addStretch()
        return page

    def _build_bots_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)

        for text, page_idx in [("Рыбалка", 5)]:
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(button_style())
            b.clicked.connect(lambda _=False, p=page_idx: self._go_to(p))
            lay.addWidget(b)

        lay.addStretch()
        return page

    def _build_fishing2_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)

        self._fish2_status = QLabel("Остановлен")
        self._fish2_status.setAlignment(Qt.AlignCenter)
        self._fish2_status.setFont(app_font(27))
        self._fish2_status.setStyleSheet("color:rgb(200,200,200);")
        lay.addWidget(self._fish2_status, 1)

        self._fish2_debug_panel = QWidget()
        dl = QVBoxLayout(self._fish2_debug_panel)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(3)

        self._fish2_slider_label = QLabel("120 мс")
        self._fish2_slider_label.setAlignment(Qt.AlignCenter)
        self._fish2_slider_label.setFont(pixel_font(16))
        self._fish2_slider_label.setStyleSheet("color:rgb(200,200,200);")
        dl.addWidget(self._fish2_slider_label)

        self._fish2_slider = QSlider(Qt.Horizontal)
        self._fish2_slider.setRange(0, 250)
        self._fish2_slider.setValue(120)
        self._fish2_slider.setSingleStep(10)
        self._fish2_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: rgb(40,40,46); height: 6px; border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: rgb(200,200,200); width: 14px; margin: -5px 0;
                border-radius: 7px;
            }
        """)
        self._fish2_slider.valueChanged.connect(self._on_fish2_slider)
        dl.addWidget(self._fish2_slider)

        saved_ms = self._load_pred_time()
        self._fish2_slider.setValue(saved_ms)
        self._state.fishing2_pred_time = saved_ms / 1000.0

        self._fish2_debug_panel.hide()
        lay.addWidget(self._fish2_debug_panel)

        self._fish2_btn = QPushButton("Старт")
        self._fish2_btn.setCursor(Qt.PointingHandCursor)
        self._fish2_btn.setStyleSheet(button_style())
        self._fish2_btn.clicked.connect(self._toggle_fishing2)
        lay.addWidget(self._fish2_btn)
        return page

    def _on_fish2_slider(self, val):
        self._fish2_slider_label.setText(f"{val} мс")
        self._state.fishing2_pred_time = val / 1000.0
        self._save_pred_time(val)

    def _save_pred_time(self, ms):
        from licensing import _load_config, _save_config
        data = _load_config()
        data["fishing_pred_ms"] = ms
        _save_config(data)

    def _load_pred_time(self):
        from licensing import _load_config
        data = _load_config()
        return data.get("fishing_pred_ms", 120)

    def _build_settings_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(5)
        btn = QPushButton("Сброс")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(button_style())
        btn.clicked.connect(self._reset_settings)
        lay.addWidget(btn)
        lay.addStretch()
        return page

    def _reset_settings(self):
        from licensing import _load_config, _save_config
        data = _load_config()
        preserved = {}
        if "activation" in data:
            preserved["activation"] = data["activation"]
        _save_config(preserved)
        s = self._state
        s.fishing2_pred_time = 0.12
        s.fishing2_bar_rect = None
        s.fishing2_debug = False
        s.fishing2_calibrated = False
        self._fish2_slider.setValue(120)
        self._go_to(0)

    def _toggle_fishing2(self):
        s = self._state
        if hasattr(self, '_fish2_countdown') and self._fish2_countdown > 0:
            self._fish2_countdown = 0
            self._fish2_cd_timer.stop()
            self._fish2_btn.setText("Старт")
            self._fish2_status.setText("Остановлен")
            s.fishing2_debug = False
            self._fish2_debug_panel.hide()
            return
        if s.fishing2_active:
            s.fishing2_active = False
            s.fishing2_debug = False
            self._fish2_debug_panel.hide()
            self._fish2_btn.setText("Старт")
            self._fish2_status.setText("Остановлен")
            self._fish2_timer.stop()
        else:
            from modules.fishing.loop import _load_bar_rect
            if _load_bar_rect() is None:
                s.fishing2_debug = True
                self._fish2_debug_panel.show()
            else:
                s.fishing2_debug = False
                self._fish2_debug_panel.hide()

            self._fish2_countdown = 3
            self._fish2_btn.setText("Стоп")
            self._fish2_status.setText("3")
            if not hasattr(self, '_fish2_cd_timer'):
                self._fish2_cd_timer = QTimer(self)
                self._fish2_cd_timer.timeout.connect(self._on_fish2_countdown)
            self._fish2_cd_timer.start(1000)

    def _on_fish2_countdown(self):
        self._fish2_countdown -= 1
        if self._fish2_countdown > 0:
            self._fish2_status.setText(str(self._fish2_countdown))
        else:
            self._fish2_cd_timer.stop()
            self._state.fishing2_active = True
            if self._state.fishing2_debug:
                self._fish2_status.setText("Калибровка")
            else:
                self._fish2_status.setText("Заброс")
            self._fish2_timer.start(33)

    def _on_fish2_tick(self):
        s = self._state
        step = s.fishing2_step
        if step in ("idle", "cast"):
            if s.fishing2_debug:
                self._fish2_status.setText("Калибровка")
            else:
                self._fish2_status.setText("Заброс")
        elif step == "strike":
            txt = "Подсечка (пузыри!)" if s.fishing2_bubbles else "Подсечка"
            self._fish2_status.setText(txt)
        elif step == "reel":
            d = s.fishing2_camera_dir
            if d == "left":
                self._fish2_status.setText("\u2190\nВытягивание")
            elif d == "right":
                self._fish2_status.setText("\u2192\nВытягивание")
            else:
                self._fish2_status.setText("Вытягивание")
        elif step == "end":
            remaining = s.fishing2_take_pause - _time.monotonic()
            if remaining > 0:
                self._fish2_status.setText(f"Пауза {remaining:.1f}с")
            else:
                self._fish2_status.setText("Забрать")
        self._overlay.sync()

    # ── Callbacks ──

    def _focus_game(self):
        from core import GAME_WINDOW_TITLE
        game_hwnd = ctypes.windll.user32.FindWindowW(None, GAME_WINDOW_TITLE)
        if not game_hwnd:
            return
        our_hwnd = int(self.winId())
        overlay_hwnd = int(self._overlay.winId()) if self._overlay else 0

        SW_MINIMIZE = 6
        keep = {game_hwnd, our_hwnd, overlay_hwnd}

        def _enum_cb(hwnd, _):
            if hwnd in keep:
                return True
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
        ctypes.windll.user32.SetForegroundWindow(game_hwnd)

    def _parse_threshold(self, text):
        t = text.strip()
        return int(t) if t.isdigit() and int(t) > 0 else 0

    def _on_queue_toggle(self, checked):
        if checked:
            self._state.notify_threshold = self._parse_threshold(self._threshold_input.text())
            self._threshold_input.setEnabled(False)
            self._state.queue_search_active = True
        else:
            self._state.queue_search_active = False
            self._threshold_input.setEnabled(True)

    def _on_stash_toggle(self, checked):
        self._state.stash_active = checked

    def _on_threshold_changed(self, text):
        self._state.notify_threshold = self._parse_threshold(text)

    def _open_queue_page(self):
        self._state.queue_page_open = True
        self._go_to(1)

    def _close_queue_page(self):
        self._state.queue_page_open = False
        self._state.queue_search_active = False
        self._go_to(2)

    def _open_items_window(self):
        if not hasattr(self, "_items_window") or self._items_window is None:
            self._items_window = ItemsWindow(self._state)
        self._items_window.show()
        self._items_window.raise_()
        self._items_window.activateWindow()
        self._items_window.load_items()

    # ── Tick (1 s) ──

    def _on_tick(self):
        self._update_game_status()
        pos = self._state.queue_position
        self._queue_label.setText(str(pos) if pos is not None else "\u2014")
        self._queue_eta.refresh(self._state)
        for w in self._stash_widgets:
            w.refresh()
        if self._state.stash_active:
            for w in self._stash_widgets:
                if w._just_opened:
                    play_click()
                    w._just_opened = False
            self._stash_float.update_timers(self._stash_widgets)
        else:
            if self._stash_float.isVisible():
                self._stash_float.hide()
        self._overlay.sync()
        self._update_markers()

    def _update_markers(self):
        if not self._state.markers_active:
            return

        s = self._state
        p = s.markers_pos
        heading = s.markers_yaw

        if p:
            self._marker_labels["X"].setText(f"X  {p[0]:.1f}")
            self._marker_labels["Y"].setText(f"Y  {p[1]:.1f}")
            self._marker_labels["Z"].setText(f"Z  {p[2]:.1f}")
        else:
            for k in ("X", "Y", "Z"):
                self._marker_labels[k].setText(f"{k}  \u2014")

        self._marker_labels["Heading"].setText(
            f"Heading  {heading:.1f}\u00b0" if heading is not None else "Heading  \u2014"
        )

    def _update_game_status(self):
        found = is_game_running()
        if found != self._game_found:
            self._game_found = found
            self.game_icon.set_color(COLOR_GREEN if found else COLOR_RED)

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
        self._stash_float.close()
        if hasattr(self, "_items_window") and self._items_window is not None:
            self._items_window.close()
        s = self._state
        s.fishing2_active = False
        s.queue_search_active = False
        if s.frame_provider.running:
            s.frame_provider.stop()
        if s.loop and s.loop.is_running():
            if s.supabase:
                asyncio.run_coroutine_threadsafe(s.supabase.close(), s.loop)
            s.loop.call_soon_threadsafe(s.loop.stop)
        super().closeEvent(ev)
