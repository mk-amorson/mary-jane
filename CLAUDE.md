# Mary Jane

Десктопное приложение-компаньон для сервера Majestic Multiplayer (GTA RP). Мониторинг очереди (OCR), таймеры тайников, автоматизация рыбалки и мини-игр (memory reading, template matching). Автономное приложение с hardware-bound лицензией (Gumroad).

## Запуск

```bash
pip install -r requirements.txt
C:\Users\mkamo\AppData\Local\Programs\Python\Python314\python.exe main.py
```

**Внешний:** Tesseract-OCR (`C:\Program Files\Tesseract-OCR\tesseract.exe`, rus+eng)
**Dev-ключ:** `MJ-DEV-2026` (bypass Gumroad, без ревалидации)

## Структура

```
main.py                       — точка входа (asyncio в bg-потоке + PyQt5 в главном)
core.py                       — AppState, GameFrameProvider (WGC), ensure_capture()
licensing.py                  — hardware fingerprint + Gumroad API + config.json
supabase_client.py            — прямой REST к Supabase (items, prices)
updater.py                    — auto-update через GitHub Releases API
version.py                    — __version__
utils.py                      — resource_path(), app_dir()
requirements.txt              — зависимости

modules/
  memory.py                   — GTA5Memory (pymem: CPed, viewport), HeadingTracker (EMA)
  input/
    sendinput.py              — Win32 PostMessage (keyboard), SendInput (mouse), vgamepad
  queue/
    monitor.py                — 2-фазный OCR + ETA, сброс при смене game_rect
  markers/
    loop.py                   — async loop: позиция/heading/camera из GTA5Memory
  fishing/
    loop.py                   — state machine: idle->cast->strike->reel->end (20-100ms tick)
    detection.py              — template match, HSV green zone/slider, Sobel edges
    trackers.py               — SliderTracker (скорость через linear regression)
    regions.py                — расчёт take_region
  toilet/
    loop.py                   — template match + zigzag drag (16ms tick)

ui/
  window.py                   — MainWindow (stacked pages, title bar, footer)
  activation.py               — ActivationDialog (лицензионный ключ)
  items.py                    — ItemsWindow (каталог предметов из Supabase)
  styles.py                   — шрифты, цвета, кешированные CSS
  sounds.py                   — click sound, ClickSoundFilter
  overlay.py                  — OverlayWindow (click-through debug overlay)
  stash.py                    — StashTimerWidget, StashFloatWindow, расписания
  markers.py                  — MarkerArrowOverlay, MarkerWorldOverlay, w2s
  queue.py                    — QueueETAWidget
  footer.py                   — FooterBar
  widgets.py                  — IconWidget, SpinningIconWidget, TitleButton, ToggleSwitch

assets/
  fonts/                      — GTA Russian.ttf, web_ibm_mda.ttf
  icons/                      — SVG/PNG (app.ico, check, factory, flask, gear, gta5, update, warning)
  sounds/                     — click.mp3
  reference/                  — PNG-шаблоны (bobber, green_bar, take, toilet, jorshik)

build.py                      — PyInstaller + Tesseract + Inno Setup
installer.iss                 — Inno Setup скрипт
mj_port.spec                  — PyInstaller spec
config.json                   — активация + калибровка (в .gitignore)
```

## Архитектура

### Потоки

- **Главный** — PyQt5 event loop (UI)
- **Фоновый** — asyncio loop, 4 корутины:
  - `queue_monitor_loop()` — OCR каждые 1 сек
  - `fishing2_bot_loop()` — рыбалка 20-100 мс
  - `toilet_bot_loop()` — чистка туалета 16 мс
  - `markers_loop()` — позиция/heading/camera 50 мс

### Связь между потоками

`AppState` — единый мутабельный объект. Поля атомарных типов (int, bool, str) безопасны через GIL. Tuple-поля (`markers_pos`, `fishing2_green_zone`) — без мьютексов.

### Общие паттерны модулей

- **Запуск бота:** `ensure_capture(state)` в `core.py` — находит HWND, ставит input target, запускает WGC, ждёт первый кадр
- **Память GTA5:** `modules/memory.py` — общий для fishing и markers
- **Ввод:** `modules/input/sendinput.py` — PostMessage (клавиатура, фоновый), SendInput (мышь), vgamepad (геймпад)
- **Template matching:** `detection.py` (fishing, single-scale с регионом), `toilet/loop.py` (multi-scale)

### Данные

- **Items/Prices** -> `SupabaseClient` (aiohttp) -> Supabase REST API (anon key, RLS public read)
- **Лицензия** -> `licensing.py` -> Gumroad verify API, hardware fingerprint, config.json
- **Обновления** -> `updater.py` -> GitHub Releases API (приватный репо, read-only token)

### Ключевые компоненты

| Компонент | Файл | Назначение |
|-----------|------|------------|
| AppState | core.py | Центральный хаб состояния |
| GameFrameProvider | core.py | WGC захват экрана, thread-safe буфер |
| ensure_capture() | core.py | Общий startup для ботов (HWND + WGC + game_rect) |
| GTA5Memory | modules/memory.py | pymem: CPed, viewport, camera vectors |
| HeadingTracker | modules/memory.py | EMA heading delta -> reel direction |
| SupabaseClient | supabase_client.py | REST клиент для items/prices |
| licensing | licensing.py | Gumroad API + hardware ID + config |

## Важно

- Python 3.14, Windows 11
- Системный python — заглушка MS Store, использовать `AppData\Local\Programs\Python\Python314\python.exe`
- Config в config.json — в .gitignore
- GitHub repo: `mk-amorson/mary-jane` (приватный), релизы через `gh release create`
- Коммиты: `v<version> <мистическое животное>` (не юмор, энергетика)
- Активация: Gumroad ключ -> hardware bind -> grace period 30 дней офлайн
- OCR работает при `queue_search_active=True`, НЕ привязан к toggle уведомлений

---

## Бренд-бук и дизайн-система

### Философия

Тёмный, минималистичный game overlay. Высокий контраст текста на тёмном фоне. Плоский дизайн без теней. Крупная типографика — читаемость с расстояния поверх GTA окна.

### Цветовая палитра

**Фоны (от тёмного к светлому):**

| Токен | RGB | Где |
|-------|-----|-----|
| bg-deep | `rgb(20, 20, 24)` | Footer |
| bg-title | `rgb(22, 22, 26)` | Title bar (ItemsWindow) |
| bg-base | `rgb(28, 28, 32)` | Основной фон виджетов |
| bg-elevated | `rgb(32, 32, 38)` | Кнопки, инпуты, карточки |
| bg-hover | `rgb(44, 44, 52)` | Hover-состояние кнопок |

**Акценты:**

| Токен | RGB | QColor | Где |
|-------|-----|--------|-----|
| accent-green | `rgb(80, 200, 80)` | `COLOR_GREEN` | Прогресс, toggle on, успех |
| accent-yellow | `rgb(220, 180, 50)` | `COLOR_YELLOW` | Предупреждения |
| accent-red | `rgb(200, 70, 70)` | `COLOR_RED` | Ошибки, закрытый тайник |

**Текст:**

| Токен | RGB | Где |
|-------|-----|-----|
| text-primary | `rgb(240, 240, 240)` | Основной текст |
| text-secondary | `rgb(220, 220, 220)` | Второстепенные лейблы |
| text-muted | `rgb(180, 180, 180)` | Footer, статус |
| text-disabled | `rgb(120, 120, 120)` | Заблокированные инпуты |

**Границы:**

| Токен | RGBA | Где |
|-------|------|-----|
| border-subtle | `rgba(255, 255, 255, 20)` | Кнопки, инпуты (1px) |
| border-top | `rgba(255, 255, 255, 15)` | Верхняя граница footer |

**Overlay (debug):**

| Элемент | Цвет |
|---------|------|
| Fishing bar | `rgb(255, 220, 50)` yellow |
| Green zone | `rgb(80, 255, 80)` bright green |
| Slider bounds | `rgb(255, 255, 255, 180)` white |
| Prediction | `rgb(255, 60, 60)` red |
| Bobber (bubbles) | `rgb(255, 165, 0)` orange |
| Bobber (normal) | `rgb(255, 80, 255)` magenta |
| Take icon | `rgb(255, 220, 50)` yellow |
| Toilet boundary | `rgb(0, 220, 255)` cyan |
| Toilet jorshik | `rgb(80, 255, 80)` green |
| Toilet path | `rgb(255, 255, 255, 40)` dim white |
| Toilet cursor | `rgb(255, 140, 0)` orange |
| Marker | `rgb(255, 255, 0)` bright yellow |

### Типографика

**Шрифты:**

| Ключ | Файл | Назначение | Fallback |
|------|------|------------|----------|
| `app` | `GTA Russian.ttf` | Заголовки, кнопки, основной текст | системный sans-serif |
| `pixel` | `web_ibm_mda.ttf` | Данные, числа, таймеры, координаты | Consolas |

**API:** `app_font(size)` и `pixel_font(size)` из `ui/styles.py`

**Размеры:**

| Контекст | Размер | Шрифт |
|----------|--------|-------|
| Кнопки | 27px | app |
| Основные лейблы | 22-27px | app |
| Таблица (items) | 20-22px | app |
| Поиск (items) | 22px | app |
| Таймеры, ETA | 19px | pixel |
| Координаты (XYZ) | 18px | pixel |
| Footer версия | 14px | pixel |
| Footer статус | 12px | pixel |

### Компоненты UI

**Кнопки:** `button_style()` из `ui/styles.py`
- Фон: `bg-elevated`, hover: `bg-hover`
- Граница: `border-subtle`, radius: 5px, padding: 5px

**Инпуты:** `input_style()` из `ui/styles.py`
- Аналогично кнопкам, padding: 3px
- Disabled: `text-disabled` на `rgb(28, 28, 34)`

**Toggle switch:** (кастомный в `ui/widgets.py`)
- Track: `rgb(60, 60, 65)` off -> `accent-green` on
- Thumb: белый круг, QPropertyAnimation

**Progress bars:** кастомная QPainter отрисовка
- Фон: белый alpha 10, заливка: `accent-green` alpha 90

**Scrollbar:** 6px, фон `bg-base`, handle `rgb(60, 60, 68)`, radius 3px

### Иконки

**Формат:** SVG (предпочтительно), PNG для растровых
**Именование:** lowercase, одно слово: `{name}.svg`
**Тонирование:** runtime через `CompositionMode_SourceIn`

| Иконка | Формат | Где |
|--------|--------|-----|
| app.ico | ICO | Иконка окна |
| check.svg | SVG | Статус обновления (успех) |
| factory.svg | SVG | Тайник (индустриальный) |
| flask.svg | SVG | Тайник (химический) |
| gear.svg | SVG | Настройки |
| gta5.png | PNG | Статус игры |
| update.svg | SVG | Спиннер обновления |
| warning.svg | SVG | Тайник (опасная зона) |

**Системные (рисуются кодом):** close (X), minimize (—)

### Окна

**MainWindow:** frameless, always-on-top, `screen_h/5` высота, правый верхний угол, alpha 230
**OverlayWindow:** click-through (`WS_EX_LAYERED | WS_EX_TRANSPARENT`), только QPainter
**ItemsWindow:** frameless, always-on-top, 750x550px

### Reference-шаблоны (template matching)

**Директория:** `assets/reference/`, формат PNG, загрузка grayscale

| Шаблон | Модуль | Порог | Масштабы |
|--------|--------|-------|----------|
| bobber.png | fishing | 0.8 | 1x (single-scale) |
| green_bar.png | fishing | 0.8 | 1x |
| take.png | fishing | 0.85 | 1x |
| toilet.png | toilet | 0.5 | 0.3-1.0 (multi-scale) |
| jorshik.png | toilet | 0.5 | 0.3-1.0 (multi-scale) |
