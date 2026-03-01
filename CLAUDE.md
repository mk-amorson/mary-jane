# MJ Port V2

Десктопное приложение-компаньон для сервера Majestic Multiplayer (GTA RP). Мониторинг очереди (OCR), таймеры тайников, автоматизация рыбалки (memory reading), auth через Telegram. Клиент-серверная архитектура.

## Запуск

### Сервер (быстрый старт)

```bash
# Вариант 1: двойной клик dev_server.bat (открывает 2 окна: uvicorn + ngrok)

# Вариант 2: вручную
C:\Users\mkamo\AppData\Local\Programs\Python\Python314\python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8000
C:\Users\mkamo\AppData\Local\ngrok\ngrok.exe http 8000 --url=axiomatic-aryana-hillocky.ngrok-free.dev
```

### Клиент

```bash
pip install -r requirements.txt
C:\Users\mkamo\AppData\Local\Programs\Python\Python314\python.exe main.py
```

**Внешний:** Tesseract-OCR (`C:\Program Files\Tesseract-OCR\tesseract.exe`, rus+eng)

### Тесты

```bash
python -m pytest tests/ -v
```

## Структура

```
main.py                       — точка входа (asyncio в bg-потоке + PyQt5 в главном)
core.py                       — AppState, GameFrameProvider (WGC), SERVER_URL из config.json
api_client.py                 — aiohttp клиент, JWT auth, auto-refresh + refresh lock
updater.py                    — проверка/скачивание обновлений через GitHub releases
version.py                    — __version__ = "1.0.3"
utils.py                      — resource_path() для PyInstaller
requirements.txt              — клиентские зависимости (pinned)
config.json                   — JWT токены + server_url + калибровка fishing (в .gitignore)

auth/
  token_store.py              — JWT persistence в config.json
  login_server.py             — localhost HTTP callback для Telegram Login Widget

modules/
  queue_monitor.py            — 2-фазный OCR + ETA, сброс при смене game_rect
  subscription.py             — SubscriptionManager (1hr cache, free/paid модули)
  input.py                    — Win32 SendInput (keyboard scancode/vkey, mouse, text)
  markers.py                  — async loop: позиция/heading/camera из GTA5Memory

  fishing/
    loop.py                   — state machine: idle→cast→strike→reel→end (50ms tick)
    detection.py              — template match, HSV green zone/slider, Sobel edges
    memory.py                 — GTA5Memory (pymem), HeadingTracker (EMA)
    trackers.py               — SliderTracker (скорость через linear regression)
    regions.py                — расчёт take_region
    input.py                  — re-export modules.input

ui/
  window.py                   — MainWindow (950 строк)
  styles.py                   — шрифты, цвета, кешированные CSS
  sounds.py                   — click sound, ClickSoundFilter
  overlay.py                  — OverlayWindow (click-through debug overlay)
  stash.py                    — StashTimerWidget, StashFloatWindow, расписания
  markers.py                  — MarkerArrowOverlay, MarkerWorldOverlay, w2s
  queue.py                    — QueueETAWidget
  footer.py                   — FooterBar
  widgets.py                  — IconWidget, SpinningIconWidget, TitleButton, ToggleSwitch

server/
  main.py                     — FastAPI + lifespan (webhook + wiki scraper)
  config.py                   — Pydantic Settings из .env
  database.py                 — Supabase REST обёртка (httpx, без SDK)
  auth/                       — Telegram Login валидация, JWT, middleware
  bot/                        — /start, /help, Stars-оплата, webhook
  routers/                    — auth, items, prices, modules, notify, app
  scraper/wiki.py             — ежедневный парсер каталога предметов

tests/                        — pytest тесты (HeadingTracker, OCR, ETA, stash, core)
supabase/migrations/          — SQL-схема
fonts/                        — GTA Russian.ttf, web_ibm_mda.ttf
icons/                        — SVG/PNG иконки
reference/                    — PNG-шаблоны для fishing
sounds/                       — click.mp3
tools/                        — debug/calibration скрипты (не продакшен)
dev_server.bat                — быстрый запуск server + ngrok (двойной клик)
```

## Архитектура

### Потоки

- **Главный** — PyQt5 event loop (UI)
- **Фоновый** — asyncio loop, 5 корутин:
  - `queue_monitor_loop()` — OCR каждые 1 сек
  - `fishing2_bot_loop()` — рыбалка каждые 50 мс
  - `auth_check_loop()` — auth + подписки каждые 30 сек
  - `markers_loop()` — позиция/heading/camera из памяти
  - `_fetch_bot_username()` — однократно при старте

### Связь между потоками

`AppState` — единый мутабельный объект. Поля атомарных типов (int, bool, str) безопасны через GIL. Tuple-поля (`markers_pos`, `fishing2_green_zone`) — без мьютексов.

### Клиент-сервер

- **Клиент** → `ApiClient` (aiohttp) → `SERVER_URL` из config.json (default: localhost:8000)
- **Сервер** → FastAPI → Supabase (httpx REST) + Telegram Bot (aiogram webhook)
- Auth: Telegram Login Widget → localhost callback → JWT (access 60min + refresh 30d)
- Подписки: Telegram Stars → server создаёт subscription
- Token refresh защищён asyncio.Lock от race condition

### Ключевые компоненты

| Компонент | Файл | Назначение |
|-----------|------|------------|
| AppState | core.py | Центральный хаб состояния |
| GameFrameProvider | core.py | WGC захват экрана, thread-safe буфер |
| ApiClient | api_client.py | HTTP + JWT auto-refresh + refresh lock |
| TokenStore | auth/token_store.py | JWT в config.json |
| SubscriptionManager | modules/subscription.py | free/paid контроль доступа |
| GTA5Memory | modules/fishing/memory.py | pymem: CPed, viewport |
| HeadingTracker | modules/fishing/memory.py | EMA heading delta → reel direction |

## OCR Pipeline

1. `find_text_region()` — полный OCR, поиск "очеред", фиксация bbox
2. `calc_number_region()` → `ocr_digits()` — быстрый OCR цифр (PSM 7, whitelist 0-9)
3. ETA: фильтр выбросов (>30), EMA rate (alpha=0.15)
4. Автосброс OCR-региона при изменении game_rect (resize/move)
5. Уведомление: POST /notify/queue или тройной beep

## Fishing Bot

State machine (50ms tick): `idle → cast → strike → reel → end → cast`
- **Cast**: SPACE, ждёт панель (GREEN_BAR_TMPL match)
- **Strike**: ждёт пузыри (HoughCircles) или heading.moving
- **Reel**: HeadingTracker → hold A/D, SliderTracker prediction
- **End**: detect take icon → click, delay → next cast

## UI (модульная структура)

- `window.py` — MainWindow (950 строк), graceful shutdown в closeEvent
- `styles.py` — шрифты (load_fonts, app_font, pixel_font), цвета, CSS
- `sounds.py` — click sound + event filter
- `overlay.py` — OverlayWindow (click-through)
- `stash.py` — StashTimerWidget + StashFloatWindow + расписания
- `markers.py` — 3D arrow overlay + world circle + w2s проекция
- `queue.py` — QueueETAWidget с прогресс-баром
- `footer.py` — FooterBar с индикатором обновления

## Шрифты

- `GTA Russian.ttf` — основной (кнопки 22px, названия 16px, порог 20px)
- `web_ibm_mda.ttf` — пиксельный моноширный (таймеры 16px)

## БД (Supabase)

users, modules (5: stash/items/queue free, fishing/sell paid), subscriptions, items (868), price_history (append-only), price_summary (materialized view, pg_cron 5min)

## Важно

- OCR работает при `queue_search_active=True`, НЕ привязан к toggle уведомлений
- `SERVER_URL` читается из config.json → `server_url`, fallback `http://localhost:8000`
- Python 3.14, Windows 11
- Системный python — заглушка MS Store, использовать `AppData\Local\Programs\Python\Python314\python.exe`
- Secrets в config.json и server/.env — оба в .gitignore
- `start_*.bat` в .gitignore — dev-скрипты называть иначе (например dev_server.bat)
- GitHub repo: `mk-amorson/mary-jane`, релизы через `gh release create`
- Бот @mj_portobot — `/start` автоматически показывает последнюю версию из GitHub Releases
- ngrok домен: `axiomatic-aryana-hillocky.ngrok-free.dev`
