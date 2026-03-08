"""Items catalog window."""

import asyncio
import json
import logging
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QComboBox, QLabel, QPushButton, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QPixmap, QIcon, QImage

import aiohttp

from licensing import _config_path
from ui.styles import app_font, _font_families
from ui.widgets import IconWidget

log = logging.getLogger(__name__)


def _load_favorites() -> set[int]:
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            return set(json.load(f).get("favorites", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_favorites(ids: set[int]):
    path = _config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}
    cfg["favorites"] = sorted(ids)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)

_CATEGORY_LABELS = {
    "food": "Продукты",
    "tool": "Инструменты",
    "fish": "Рыба",
    "equipment": "Оборудование",
    "alcohol": "Алкоголь",
    "ammunition": "Амуниция",
    "medical": "Медицина",
    "auto_parts": "Автозапчасти",
    "misc": "Прочее",
    "consumables": "Расходники",
    "facilities": "Инфраструктура",
    "documents": "Документы",
    "books": "Книги",
    "personals": "Личные вещи",
    "products": "Продукция",
    "materials": "Материалы",
    "clothes": "Одежда",
    "rubbish": "Мусор",
    "agriculture": "Сельское хозяйство",
    "drugs": "Стафф",
    "ingredients": "Ингредиенты",
    "armor": "Броня",
    "others": "Разное",
}

_IMG_SIZE = 40
_PLACEHOLDER = None


def _placeholder() -> QPixmap:
    global _PLACEHOLDER
    if _PLACEHOLDER is None:
        _PLACEHOLDER = QPixmap(_IMG_SIZE, _IMG_SIZE)
        _PLACEHOLDER.fill(QColor(40, 40, 46))
    return _PLACEHOLDER


def _ff():
    return f"font-family: '{_font_families['app']}';" if _font_families.get("app") else ""


_WINDOW_CSS = """
    QWidget#ItemsRoot {
        background: rgb(28, 28, 32);
    }
    QLineEdit {
        background: rgb(32, 32, 38); color: rgb(240, 240, 240);
        border: 1px solid rgba(255, 255, 255, 20); border-radius: 5px;
        padding: 4px 8px; font-size: 22px;
    }
    QComboBox {
        background: rgb(32, 32, 38); color: rgb(240, 240, 240);
        border: 1px solid rgba(255, 255, 255, 20); border-radius: 5px;
        padding: 4px 8px; font-size: 22px;
    }
    QComboBox::drop-down {
        border: none; width: 0; padding: 0; margin: 0;
    }
    QComboBox::down-arrow {
        image: none; width: 0; height: 0;
    }
    QComboBox QAbstractItemView {
        background: rgb(32, 32, 38); color: rgb(240, 240, 240);
        selection-background-color: rgb(50, 50, 58);
        border: 1px solid rgba(255, 255, 255, 20);
        outline: none; font-size: 22px;
        text-align: left;
    }
    QTableWidget {
        background: rgb(28, 28, 32); color: rgb(240, 240, 240);
        border: none; gridline-color: rgba(255, 255, 255, 12);
        selection-background-color: rgb(44, 44, 52);
    }
    QTableWidget::item { padding: 2px 6px; }
    QHeaderView::section {
        background: rgb(32, 32, 38); color: rgb(180, 180, 180);
        border: none; border-bottom: 1px solid rgba(255, 255, 255, 20);
        padding: 4px 8px; font-size: 20px;
    }
    QScrollBar:vertical {
        background: rgb(28, 28, 32); width: 8px; border: none;
    }
    QScrollBar::handle:vertical {
        background: rgb(60, 60, 68); border-radius: 4px; min-height: 30px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
"""


class ItemsWindow(QWidget):
    _sig_items_loaded = pyqtSignal(list)
    _sig_image_ready = pyqtSignal(int, QPixmap)  # item_id, pixmap

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self._state = state
        self._all_items: list[dict] = []
        self._categories: list[str] = []
        self._sort_col = 1  # name
        self._sort_asc = True
        self._image_cache: dict[int, QPixmap] = {}
        self._favorites: set[int] = _load_favorites()
        self._show_favorites = False
        self._drag_pos = None

        self.setObjectName("ItemsRoot")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFixedSize(750, 550)

        self._sig_items_loaded.connect(self._on_items_loaded)
        self._sig_image_ready.connect(self._on_image_ready)

        self._build_ui()

        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_filters)

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # title bar
        title_bar = QWidget()
        title_bar.setFixedHeight(36)
        title_bar.setStyleSheet("background: rgb(22, 22, 26);")
        tb_lay = QHBoxLayout(title_bar)
        tb_lay.setContentsMargins(12, 0, 4, 0)

        lbl = QLabel("Предметы")
        lbl.setFont(app_font(27))
        lbl.setStyleSheet("color: rgb(240, 240, 240);")
        tb_lay.addWidget(lbl)
        tb_lay.addStretch()

        close_btn = QPushButton()
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 15); border-radius: 4px; }"
        )
        close_icon = IconWidget("close")
        close_icon.setFixedSize(28, 28)
        cl = QHBoxLayout(close_btn)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(close_icon)
        close_btn.clicked.connect(self.close)
        tb_lay.addWidget(close_btn)

        root.addWidget(title_bar)

        # toolbar
        toolbar = QWidget()
        toolbar.setStyleSheet("background: rgb(28, 28, 32);")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(6)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Поиск по названию…")
        self._search_input.setFont(app_font(22))
        self._search_input.textChanged.connect(lambda: self._search_timer.start())
        tl.addWidget(self._search_input, 1)

        self._cat_combo = QComboBox()
        self._cat_combo.setFont(app_font(22))
        self._cat_combo.setMinimumWidth(200)
        self._cat_combo.addItem("Все категории")
        self._cat_combo.currentIndexChanged.connect(lambda _: self._apply_filters())
        tl.addWidget(self._cat_combo)

        self._fav_btn = QPushButton("\u2606")
        self._fav_btn.setFont(app_font(24))
        self._fav_btn.setFixedSize(36, 36)
        self._fav_btn.setCursor(Qt.PointingHandCursor)
        self._fav_btn.setStyleSheet(
            "QPushButton { background: rgb(32, 32, 38); color: rgb(160, 160, 160);"
            "  border: 1px solid rgba(255, 255, 255, 20); border-radius: 5px; }"
            "QPushButton:hover { background: rgb(44, 44, 52); }"
        )
        self._fav_btn.setToolTip("Избранное")
        self._fav_btn.clicked.connect(self._toggle_favorites)
        tl.addWidget(self._fav_btn)

        root.addWidget(toolbar)

        # count label
        self._count_label = QLabel("")
        self._count_label.setFont(app_font(20))
        self._count_label.setStyleSheet(
            "color: rgb(140, 140, 140); padding: 2px 10px; background: rgb(28, 28, 32);"
        )
        root.addWidget(self._count_label)

        # table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setIconSize(QSize(_IMG_SIZE, _IMG_SIZE))

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        self._table.setColumnWidth(0, _IMG_SIZE + 12)
        self._table.setColumnWidth(2, 200)
        self._table.setColumnWidth(3, 36)
        hdr.sectionClicked.connect(self._on_header_clicked)
        self._update_header_labels()
        self._table.cellClicked.connect(self._on_cell_clicked)

        self._table.verticalHeader().setDefaultSectionSize(_IMG_SIZE + 6)

        root.addWidget(self._table, 1)

        self.setStyleSheet(_WINDOW_CSS)

    # ── Data loading ──────────────────────────────────────

    def load_items(self):
        loop = self._state.loop
        sb = self._state.supabase
        if not loop or not sb:
            return
        asyncio.run_coroutine_threadsafe(self._fetch_all(sb), loop)

    async def _fetch_all(self, sb):
        items = await sb.get_items()
        self._sig_items_loaded.emit(items)

    def _on_items_loaded(self, items: list):
        self._all_items = items

        cats = sorted({it.get("category", "") for it in items if it.get("category")},
                       key=lambda c: _CATEGORY_LABELS.get(c, c))
        self._categories = cats
        self._cat_combo.blockSignals(True)
        self._cat_combo.clear()
        self._cat_combo.addItem("Все категории")
        for c in cats:
            self._cat_combo.addItem(_CATEGORY_LABELS.get(c, c))
        self._cat_combo.blockSignals(False)

        self._apply_filters()
        self._load_images(items)

    # ── Filtering / sorting ───────────────────────────────

    def _toggle_favorites(self):
        self._show_favorites = not self._show_favorites
        self._fav_btn.setText("\u2605" if self._show_favorites else "\u2606")
        self._fav_btn.setStyleSheet(
            "QPushButton { background: rgb(32, 32, 38);"
            f"  color: {'rgb(255, 200, 60)' if self._show_favorites else 'rgb(160, 160, 160)'};"
            "  border: 1px solid rgba(255, 255, 255, 20); border-radius: 5px; }"
            "QPushButton:hover { background: rgb(44, 44, 52); }"
        )
        self._apply_filters()

    def _on_cell_clicked(self, row: int, col: int):
        if col != 3:
            return
        name_item = self._table.item(row, 1)
        if not name_item:
            return
        item_id = name_item.data(Qt.UserRole)
        if item_id in self._favorites:
            self._favorites.discard(item_id)
        else:
            self._favorites.add(item_id)
        _save_favorites(self._favorites)
        star = self._table.item(row, 3)
        if star:
            is_fav = item_id in self._favorites
            star.setText("\u2605" if is_fav else "\u2606")
            star.setForeground(QColor(255, 200, 60) if is_fav else QColor(80, 80, 80))
        if self._show_favorites:
            self._apply_filters()

    def _filtered_items(self) -> list[dict]:
        items = self._all_items

        if self._show_favorites:
            items = [it for it in items if it.get("id", 0) in self._favorites]

        search = self._search_input.text().strip().lower()
        if search:
            items = [it for it in items if search in it.get("name", "").lower()]

        cat_idx = self._cat_combo.currentIndex()
        if cat_idx > 0:
            cat = self._categories[cat_idx - 1]
            items = [it for it in items if it.get("category") == cat]

        key = "name" if self._sort_col == 1 else "category"
        items = sorted(items, key=lambda it: (it.get(key) or "").lower(), reverse=not self._sort_asc)
        return items

    def _apply_filters(self):
        items = self._filtered_items()
        self._count_label.setText(f"  {len(items)} из {len(self._all_items)}")
        self._populate_table(items)

    def _populate_table(self, items: list[dict]):
        self._table.setRowCount(len(items))
        for row, it in enumerate(items):
            item_id = it.get("id", 0)

            # icon column
            icon_item = QTableWidgetItem()
            pix = self._image_cache.get(item_id, _placeholder())
            icon_item.setIcon(QIcon(pix))
            icon_item.setFlags(Qt.ItemIsEnabled)
            self._table.setItem(row, 0, icon_item)

            # name
            name_item = QTableWidgetItem(it.get("name", ""))
            name_item.setFont(app_font(22))
            name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            name_item.setData(Qt.UserRole, item_id)
            self._table.setItem(row, 1, name_item)

            # category
            raw_cat = it.get("category", "")
            cat_item = QTableWidgetItem(_CATEGORY_LABELS.get(raw_cat, raw_cat))
            cat_item.setFont(app_font(22))
            cat_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            cat_item.setForeground(QColor(160, 160, 160))
            self._table.setItem(row, 2, cat_item)

            # favorite star
            is_fav = item_id in self._favorites
            star_item = QTableWidgetItem("\u2605" if is_fav else "\u2606")
            star_item.setFont(app_font(22))
            star_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            star_item.setForeground(QColor(255, 200, 60) if is_fav else QColor(80, 80, 80))
            star_item.setFlags(Qt.ItemIsEnabled)
            self._table.setItem(row, 3, star_item)

    def _update_header_labels(self):
        labels = ["", "Название", "Категория", ""]
        for i in (1, 2):
            if i == self._sort_col:
                labels[i] += "  \u25B2" if self._sort_asc else "  \u25BC"
        self._table.setHorizontalHeaderLabels(labels)

    def _on_header_clicked(self, col: int):
        if col == 0:
            return
        if col == self._sort_col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._update_header_labels()
        self._apply_filters()

    # ── Image loading ─────────────────────────────────────

    def _load_images(self, items: list[dict]):
        loop = self._state.loop
        if not loop:
            return
        urls = []
        for it in items:
            url = it.get("image_url")
            if url:
                urls.append((it["id"], url))
        if urls:
            asyncio.run_coroutine_threadsafe(self._download_images(urls), loop)

    async def _download_images(self, urls: list[tuple[int, str]]):
        sem = asyncio.Semaphore(20)

        async def _fetch_one(session, item_id, url):
            async with sem:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            img = QImage()
                            if img.loadFromData(data):
                                pix = QPixmap.fromImage(img).scaled(
                                    _IMG_SIZE, _IMG_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation,
                                )
                                self._sig_image_ready.emit(item_id, pix)
                except Exception:
                    pass

        async with aiohttp.ClientSession() as session:
            tasks = [_fetch_one(session, iid, u) for iid, u in urls]
            await asyncio.gather(*tasks)

    def _on_image_ready(self, item_id: int, pix: QPixmap):
        self._image_cache[item_id] = pix
        # update visible rows that match this item_id
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 1)
            if name_item and name_item.data(Qt.UserRole) == item_id:
                self._table.item(row, 0).setIcon(QIcon(pix))
                break

    # ── Dragging ──────────────────────────────────────────

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and ev.pos().y() < 36:
            self._drag_pos = ev.globalPos() - self.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag_pos and ev.buttons() == Qt.LeftButton:
            self.move(ev.globalPos() - self._drag_pos)
            ev.accept()

    def mouseReleaseEvent(self, _ev):
        self._drag_pos = None
