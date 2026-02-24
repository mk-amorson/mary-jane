# MJ Port V2

Десктопное приложение для мониторинга очереди на сервере Majestic Multiplayer (GTA RP). OCR читает позицию в очереди с экрана игры, уведомляет через Telegram или звуковой сигнал. Таймеры тайников с прогресс-барами.

## Запуск

```bash
C:\Users\mkamo\AppData\Local\Programs\Python\Python314\python.exe main.py
```

**Зависимости:** PyQt5, aiogram 3.x, pytesseract, Pillow, windows-capture, pywin32

**Внешние:** Tesseract-OCR (`C:\Program Files\Tesseract-OCR\tesseract.exe`, языки: rus+eng)

## Структура

```
main.py                  — точка входа (asyncio loop в фоновом потоке + PyQt5 в главном)
core.py                  — AppState (центральный хаб), GameFrameProvider (WGC), game detection
bot.py                   — Telegram-бот (aiogram 3.x), /screenshot
modules/queue_monitor.py — 2-фазный OCR: поиск текста → извлечение цифр
ui/window.py             — MainWindow, OverlayWindow, StashTimerWidget
ui/widgets.py            — IconWidget, TitleButton, ToggleSwitch
fonts/GTA Russian.ttf    — основной шрифт UI
fonts/web_ibm_mda.ttf    — пиксельный моноширный шрифт для таймеров тайников
icons/                   — SVG иконки (gta5.svg, telegram.svg)
```

## Архитектура

### Потоки

- **Главный поток** — PyQt5 event loop (UI)
- **Фоновый поток** — asyncio loop с двумя корутинами:
  - `queue_monitor_loop()` — OCR мониторинг каждые 1 сек
  - `telegram_manager()` — динамический старт/стоп бот-поллинга

### Связь между потоками

`AppState` (core.py) — единый объект состояния, доступен обоим потокам. Поля читаются/пишутся напрямую (атомарные типы Python). Нет мьютексов кроме `GameFrameProvider._lock` для фрейм-буфера.

### Компоненты

- **AppState** (core.py) — все флаги, пороги, OCR-регионы, ссылки на бот/loop
- **GameFrameProvider** (core.py) — захват экрана через Windows Graphics Capture API, thread-safe доступ к фреймам
- **MainWindow** (ui/window.py) — квадратное окно (screen.height()//6), QStackedWidget с 4 страницами
- **OverlayWindow** (ui/window.py) — прозрачное click-through окно, рисует жёлтый прямоугольник вокруг OCR-региона

## OCR Pipeline (modules/queue_monitor.py)

1. **Фаза 1 (поиск текста):** `find_text_region()` — OCR всего изображения (pytesseract, rus+eng) → ищем "очеред" как якорь → находим bbox фразы → фиксируем (`ocr_text_locked=True`), выполняется один раз
2. **Фаза 2 (быстрая):** `calc_number_region()` вычисляет кроп справа от текста → `ocr_digits()` OCR только цифр (whitelist 0-9, psm 7) → `queue_position`
3. **Уведомление:** если позиция < порога → Telegram сообщение (или тройной beep если TG недоступен)

## UI

### Окно

- Квадрат screen.height()//6, правый верхний угол, opacity 0.9
- Тёмная тема: bg `rgb(28,28,32)`, текст `rgb(200,200,200)`
- Frameless, draggable, always-on-top

### Title bar

- **Левая часть** (фикс. ширина): кнопка «назад» (скрыта на главной)
- **Центр**: иконки GTA (зелёная/красная = игра найдена/нет) и Telegram (красная/жёлтая/зелёная = выкл/connecting/connected), кликабельная
- **Правая часть** (фикс. ширина = левая): minimize + close

### Страницы (QStackedWidget)

- **0 — Меню**: кнопки «Очередь», «Хелпер»
- **1 — Очередь**: большая цифра позиции (font: win_size//3), toggle поиска, поле порога
- **2 — Хелпер**: кнопка «Тайники»
- **3 — Тайники**: 4 строки StashTimerWidget с прогресс-барами

### Навигация

`_BACK` map: {1→_close_queue_page, 2→0, 3→2}. Кнопка назад в title bar, `_go_to()` управляет стеком и видимостью кнопки.

### StashTimerWidget

- Прогресс-бар на всю ширину строки (custom paintEvent)
- Фон: `rgba(255,255,255,10)`, заливка: зелёная (открыт) / красная (закрыт), alpha=90
- Обводка: зелёная/красная, border-radius=4
- Бар всегда заполняется слева направо (0% в начале периода → 100% к концу)
- Цикл рассчитывается из расписания часов: cycle = (hours[1]-hours[0])*3600
- Текст (название + таймер) белый, поверх бара
- Таймер: пиксельный шрифт web_ibm_mda.ttf, 16px

### Шрифты

- `GTA Russian.ttf` — основной UI (кнопки 22px, названия тайников 16px, порог-лейбл 20px)
- `web_ibm_mda.ttf` — пиксельный моноширный, таймеры тайников 16px
- Загрузка через `_load_fonts()` → `_font_families` dict, кешируется

### Стили

- `_button_style()` / `_input_style()` — кешируемые CSS-строки для QPushButton / QLineEdit

## Telegram-бот (bot.py)

- aiogram 3.x, диспетчер с хэндлерами
- `/screenshot` — захват экрана игры, отправка как фото
- `telegram_manager()` — следит за `state.telegram_enabled`, динамически стартует/стопит поллинг
- `chat_id` сохраняется при первом сообщении от пользователя

## Тик (1 сек, MainWindow._on_tick)

1. Проверка `is_game_running()` → обновление иконки GTA
2. Обновление цвета иконки Telegram (с кешем `_tg_color`)
3. Обновление текста позиции очереди
4. Refresh всех StashTimerWidget
5. Sync OverlayWindow с окном игры

## Важно

- **BOT_TOKEN** в `core.py:15` — не коммитить в публичные репозитории
- OCR работает при `queue_search_active=True`, НЕ привязан к toggle уведомлений
- Toggle уведомлений управляет только отправкой в Telegram
- Python 3.14, Windows 11
- Системный python (`AppData\Local\Microsoft\WindowsApps\python`) — заглушка Microsoft Store, использовать `AppData\Local\Programs\Python\Python314\python.exe`
