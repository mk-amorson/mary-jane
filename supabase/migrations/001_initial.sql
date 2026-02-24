-- ============================================================
-- MJ Port V2 — Initial Supabase Migration
-- ============================================================

-- 1. USERS
CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL UNIQUE,
    username    TEXT,
    first_name  TEXT,
    photo_url   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_banned   BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_users_telegram_id ON users (telegram_id);

-- 2. MODULES
CREATE TABLE modules (
    id           TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    description  TEXT,
    price_stars  INTEGER NOT NULL DEFAULT 0,
    is_free      BOOLEAN NOT NULL DEFAULT TRUE,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order   INTEGER NOT NULL DEFAULT 0
);

INSERT INTO modules (id, display_name, description, price_stars, is_free, sort_order) VALUES
    ('stash',   'Тайники',  'Таймеры тайников с прогресс-барами',           0, TRUE,  1),
    ('items',   'Предметы',  'Каталог предметов с ценами',                   0, TRUE,  2),
    ('queue',   'Очередь',   'Мониторинг позиции в очереди',                 0, TRUE,  3),
    ('fishing', 'Рыбалка',   'Автоматизация рыбалки',                      100, FALSE, 4),
    ('sell',    'Продажа',   'Автоматизация продажи на маркетплейсе',      100, FALSE, 5);

-- 3. SUBSCRIPTIONS
CREATE TABLE subscriptions (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module_id      TEXT NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    starts_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL,
    stars_paid     INTEGER NOT NULL DEFAULT 0,
    transaction_id TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, module_id, transaction_id)
);

CREATE INDEX idx_subscriptions_user_id ON subscriptions (user_id);
CREATE INDEX idx_subscriptions_expires ON subscriptions (expires_at);

-- 4. ITEMS (catalog from wiki)
CREATE TABLE items (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    category      TEXT,
    detail_url    TEXT,
    image_url     TEXT,
    has_min_price BOOLEAN NOT NULL DEFAULT FALSE,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_items_category ON items (category);
CREATE INDEX idx_items_has_min_price ON items (has_min_price);

-- 5. PRICE HISTORY (append-only)
CREATE TABLE price_history (
    id          BIGSERIAL PRIMARY KEY,
    item_id     INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    server_name TEXT NOT NULL,
    price       INTEGER NOT NULL,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source      TEXT NOT NULL CHECK (source IN ('sell', 'scan')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_price_history_item_server ON price_history (item_id, server_name);
CREATE INDEX idx_price_history_created ON price_history (created_at);

-- 6. PRICE SUMMARY (materialized view, refreshed by cron)
CREATE MATERIALIZED VIEW price_summary AS
SELECT
    ph.item_id,
    ph.server_name,
    -- last price: the most recent price entry
    (SELECT ph2.price
     FROM price_history ph2
     WHERE ph2.item_id = ph.item_id AND ph2.server_name = ph.server_name
     ORDER BY ph2.created_at DESC LIMIT 1
    ) AS last_price,
    -- median over last 7 days
    (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY ph3.price)
     FROM price_history ph3
     WHERE ph3.item_id = ph.item_id
       AND ph3.server_name = ph.server_name
       AND ph3.created_at >= now() - INTERVAL '7 days'
    ) AS median_7d,
    MAX(ph.created_at) AS last_updated
FROM price_history ph
GROUP BY ph.item_id, ph.server_name;

CREATE UNIQUE INDEX idx_price_summary_item_server
    ON price_summary (item_id, server_name);

-- 7. APP VERSIONS
CREATE TABLE app_versions (
    version      TEXT PRIMARY KEY,
    download_url TEXT NOT NULL,
    changelog    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_latest    BOOLEAN NOT NULL DEFAULT FALSE
);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE modules ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_versions ENABLE ROW LEVEL SECURITY;

-- modules: public read
CREATE POLICY "modules_public_read" ON modules
    FOR SELECT USING (TRUE);

-- items: public read
CREATE POLICY "items_public_read" ON items
    FOR SELECT USING (TRUE);

-- app_versions: public read
CREATE POLICY "app_versions_public_read" ON app_versions
    FOR SELECT USING (TRUE);

-- price_history: public read
CREATE POLICY "price_history_public_read" ON price_history
    FOR SELECT USING (TRUE);

-- price_history: authenticated write
CREATE POLICY "price_history_auth_insert" ON price_history
    FOR INSERT WITH CHECK (auth.role() = 'authenticated');

-- subscriptions: users read only their own
CREATE POLICY "subscriptions_own_read" ON subscriptions
    FOR SELECT USING (user_id = (
        SELECT id FROM users WHERE telegram_id = (auth.jwt() ->> 'telegram_id')::BIGINT
    ));

-- users: read own
CREATE POLICY "users_own_read" ON users
    FOR SELECT USING (telegram_id = (auth.jwt() ->> 'telegram_id')::BIGINT);

-- ============================================================
-- FUNCTION: Refresh price_summary (called by pg_cron)
-- ============================================================
CREATE OR REPLACE FUNCTION refresh_price_summary()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY price_summary;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Schedule: REFRESH every 5 minutes (requires pg_cron extension)
-- Run in Supabase SQL editor after enabling pg_cron:
-- SELECT cron.schedule('refresh_price_summary', '*/5 * * * *', 'SELECT refresh_price_summary()');
