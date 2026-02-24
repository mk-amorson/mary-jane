import os
import json
import sqlite3
import threading
import logging

log = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_DB_PATH = os.path.join(_ROOT, "marketplace.db")
_CFG_PATH = os.path.join(_ROOT, "config.json")
_local = threading.local()


def _conn():
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(_DB_PATH)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.row_factory = sqlite3.Row
        _local.conn = c
    return c


def init_db():
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            detail_url TEXT
        );
        CREATE TABLE IF NOT EXISTS prices (
            item_id INTEGER NOT NULL,
            server TEXT NOT NULL,
            in_sale INTEGER DEFAULT 0,
            sold INTEGER DEFAULT 0,
            avg_price INTEGER DEFAULT 0,
            min_price INTEGER DEFAULT 0,
            max_price INTEGER DEFAULT 0,
            updated_at TEXT,
            source TEXT DEFAULT 'site',
            PRIMARY KEY (item_id, server),
            FOREIGN KEY (item_id) REFERENCES items(id)
        );
    """)
    c.commit()
    # migrate: add columns if missing (existing DB)
    cols = {r[1] for r in c.execute("PRAGMA table_info(prices)").fetchall()}
    if "updated_at" not in cols:
        c.execute("ALTER TABLE prices ADD COLUMN updated_at TEXT")
    if "source" not in cols:
        c.execute("ALTER TABLE prices ADD COLUMN source TEXT DEFAULT 'site'")
    c.commit()


def upsert_item(item_id, name, category, detail_url):
    c = _conn()
    c.execute(
        "INSERT INTO items (id, name, category, detail_url) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
        "category=excluded.category, detail_url=excluded.detail_url",
        (item_id, name, category, detail_url),
    )
    c.commit()


def upsert_prices(item_id, rows):
    """rows: list of (server, in_sale, sold, avg_price, min_price, max_price)"""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
    c = _conn()
    c.executemany(
        "INSERT INTO prices (item_id, server, in_sale, sold, avg_price, min_price, max_price, "
        "updated_at, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'site') "
        "ON CONFLICT(item_id, server) DO UPDATE SET "
        "in_sale=excluded.in_sale, sold=excluded.sold, avg_price=excluded.avg_price, "
        "min_price=excluded.min_price, max_price=excluded.max_price, "
        "updated_at=excluded.updated_at, source=excluded.source",
        [(item_id, *r, now) for r in rows],
    )
    c.commit()


def get_items_with_prices(server, category=None):
    """Return list of tuples (id, name, cat, avg, min, max, in_sale, sold, updated_at, source)."""
    c = _conn()
    sql = (
        "SELECT i.id, i.name, i.category, "
        "COALESCE(p.avg_price, 0), COALESCE(p.min_price, 0), COALESCE(p.max_price, 0), "
        "COALESCE(p.in_sale, 0), COALESCE(p.sold, 0), "
        "p.updated_at, COALESCE(p.source, 'site') "
        "FROM items i LEFT JOIN prices p ON i.id = p.item_id AND p.server = ? "
    )
    params = [server]
    if category:
        sql += "WHERE i.category = ? "
        params.append(category)
    sql += "ORDER BY i.name"
    return [tuple(r) for r in c.execute(sql, params).fetchall()]


def get_all_item_names():
    c = _conn()
    return [(r[0], r[1]) for r in c.execute("SELECT id, name FROM items ORDER BY id").fetchall()]


def load_config():
    """Load user config. Returns dict with defaults."""
    defaults = {"mp_server": 0, "mp_category": 0}
    try:
        with open(_CFG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        defaults.update(data)
    except Exception:
        pass
    return defaults


def save_config(cfg):
    """Save user config dict to JSON."""
    try:
        with open(_CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except Exception:
        log.exception("Failed to save config")
