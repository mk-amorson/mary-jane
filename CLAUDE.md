# Mary Jane

Десктопное приложение-компаньон для сервера Majestic Multiplayer (GTA RP). Мониторинг очереди (OCR), таймеры тайников, автоматизация рыбалки (memory reading). Автономное приложение с hardware-bound лицензией (Gumroad).

## Запуск

```bash
pip install -r requirements.txt
C:\Users\mkamo\AppData\Local\Programs\Python\Python314\python.exe main.py
```

**Внешний:** Tesseract-OCR (`C:\Program Files\Tesseract-OCR\tesseract.exe`, rus+eng)

## Структура

```
main.py                       — точка входа (asyncio в bg-потоке + PyQt5 в главном)
core.py                       — AppState, GameFrameProvider (WGC)
licensing.py                  — hardware fingerprint + Gumroad API + config.json
supabase_client.py            — прямой REST к Supabase (items, prices)
updater.py                    — auto-update через GitHub Releases API
version.py                    — __version__ = "0.1.0"
utils.py                      — resource_path() для PyInstaller
requirements.txt              — зависимости

modules/
  input/
    sendinput.py              — Win32 SendInput (keyboard scancode/vkey, mouse, text)
  queue/
    monitor.py                — 2-фазный OCR + ETA, сброс при смене game_rect
  markers/
    loop.py                   — async loop: позиция/heading/camera из GTA5Memory
  fishing/
    loop.py                   — state machine: idle→cast→strike→reel→end (50ms tick)
    detection.py              — template match, HSV green zone/slider, Sobel edges
    memory.py                 — GTA5Memory (pymem), HeadingTracker (EMA)
    trackers.py               — SliderTracker (скорость через linear regression)
    regions.py                — расчёт take_region
    input.py                  — re-export modules.input

ui/
  window.py                   — MainWindow
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
  icons/                      — SVG/PNG иконки
  sounds/                     — click.mp3
  reference/                  — PNG-шаблоны для fishing

build.py                      — PyInstaller + Tesseract + Inno Setup
installer.iss                 — Inno Setup скрипт
mj_port.spec                  — PyInstaller spec
config.json                   — активация + калибровка (в .gitignore)
```

## Архитектура

### Потоки

- **Главный** — PyQt5 event loop (UI)
- **Фоновый** — asyncio loop, 3 корутины:
  - `queue_monitor_loop()` — OCR каждые 1 сек
  - `fishing2_bot_loop()` — рыбалка каждые 50 мс
  - `markers_loop()` — позиция/heading/camera из памяти

### Связь между потоками

`AppState` — единый мутабельный объект. Поля атомарных типов (int, bool, str) безопасны через GIL. Tuple-поля (`markers_pos`, `fishing2_green_zone`) — без мьютексов.

### Данные

- **Items/Prices** → `SupabaseClient` (aiohttp) → Supabase REST API (anon key, RLS public read)
- **Лицензия** → `licensing.py` → Gumroad verify API, hardware fingerprint, config.json
- **Обновления** → `updater.py` → GitHub Releases API (приватный репо, read-only token)

### Ключевые компоненты

| Компонент | Файл | Назначение |
|-----------|------|------------|
| AppState | core.py | Центральный хаб состояния |
| GameFrameProvider | core.py | WGC захват экрана, thread-safe буфер |
| SupabaseClient | supabase_client.py | REST клиент для items/prices |
| licensing | licensing.py | Gumroad API + hardware ID + config |
| GTA5Memory | modules/fishing/memory.py | pymem: CPed, viewport |
| HeadingTracker | modules/fishing/memory.py | EMA heading delta → reel direction |

## Важно

- OCR работает при `queue_search_active=True`, НЕ привязан к toggle уведомлений
- Python 3.14, Windows 11
- Системный python — заглушка MS Store, использовать `AppData\Local\Programs\Python\Python314\python.exe`
- Config в config.json — в .gitignore
- GitHub repo: `mk-amorson/mary-jane` (приватный), релизы через `gh release create`
- Коммиты: `v<version> <мистическое животное>` (не юмор, энергетика)
- Активация: Gumroad ключ → hardware bind → grace period 30 дней офлайн
