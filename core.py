import io
import time
import ctypes
import asyncio
import threading
import logging
from PIL import Image

from windows_capture import WindowsCapture, Frame, InternalCaptureControl, CaptureControl

user32 = ctypes.windll.user32
log = logging.getLogger(__name__)

GAME_WINDOW_TITLE = "Majestic Multiplayer"
SERVER_URL = "https://axiomatic-aryana-hillocky.ngrok-free.dev"


def is_game_running():
    hwnd = user32.FindWindowW(None, GAME_WINDOW_TITLE)
    return hwnd != 0


def get_game_rect():
    import win32gui
    hwnd = user32.FindWindowW(None, GAME_WINDOW_TITLE)
    if not hwnd:
        return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return (left, top, right - left, bottom - top)


class GameFrameProvider:
    """Single capture module via WGC API. No flickering."""

    def __init__(self, window_name: str):
        self._window_name = window_name
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._control: CaptureControl | None = None

    @property
    def running(self):
        return self._running

    def start(self):
        if self._running:
            return
        self._running = True
        log.info("GameFrameProvider starting for '%s'", self._window_name)

        provider = self

        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            window_name=self._window_name,
        )

        @capture.event
        def on_frame_arrived(frame: Frame, capture_control: InternalCaptureControl):
            arr = frame.frame_buffer.copy()
            with provider._lock:
                provider._frame = arr

        @capture.event
        def on_closed():
            provider._running = False
            provider._frame = None
            provider._control = None
            log.info("GameFrameProvider stopped")

        try:
            self._control = capture.start_free_threaded()
        except Exception:
            log.exception("GameFrameProvider failed to start")
            self._running = False

    def stop(self):
        if self._control:
            self._control.stop()
            self._control = None
        self._running = False
        self._frame = None

    def get_image(self) -> Image.Image | None:
        with self._lock:
            arr = self._frame
        if arr is None:
            return None
        rgb = arr[:, :, 2::-1]
        return Image.fromarray(rgb)

    def get_png(self) -> io.BytesIO | None:
        img = self.get_image()
        if img is None:
            return None
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    def ensure_running_and_grab(self, timeout: float = 2.0) -> io.BytesIO | None:
        """Start if needed, wait for a frame, return PNG. For one-off use."""
        was_stopped = not self._running
        if was_stopped:
            self.start()

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.get_png()
            if result is not None:
                return result
            time.sleep(0.1)

        return None


class AppState:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        # Auth / Server
        self.api_client = None       # ApiClient, set from main.py
        self.token_store = None      # TokenStore, set from main.py
        self.user_info: dict | None = None
        self.is_authenticated: bool = False
        self.server_url: str = SERVER_URL
        self.bot_username: str = ""
        # Subscription
        self.subscription_manager = None  # SubscriptionManager, set from main.py
        # Queue OCR (toggle on queue page)
        self.queue_page_open: bool = False
        self.queue_search_active: bool = False
        self.notify_threshold: int = 30
        self.queue_position: int | None = None
        # OCR regions
        self.game_rect: tuple | None = None
        self.ocr_text_region: tuple | None = None
        self.ocr_number_region: tuple | None = None
        self.ocr_text_locked: bool = False
        # WGC frame provider (single capture module)
        self.frame_provider: GameFrameProvider = GameFrameProvider(GAME_WINDOW_TITLE)
        # Fishing bot
        self.fishing_active: bool = False
        self.fishing_step: str = "idle"              # idle / init / cast / strike / reel / take
        self.fishing_squares: list | None = None     # locked once
        self.fishing_bar_rect: tuple | None = None   # locked slider bar
        self.fishing_green_zone: tuple | None = None # per-frame
        self.fishing_slider_x: int | None = None     # per-frame
        self.fishing_space_icon: tuple | None = None  # space icon match
        self.fishing_bobber_rect: tuple | None = None # gray square around bobber
        self.fishing_bubbles: bool = False
        self.fishing_ad_icon: tuple | None = None    # a-d icon match
        self.fishing_camera_dir: str | None = None   # left / right
        self.fishing_take_icon: tuple | None = None  # take icon match
        self.fishing_take_pause: float = 0.0         # monotonic time until pause ends
        self.fishing_bounds = None                     # SquareBounds | None, cached
        # Queue ETA (EMA-based)
        self.queue_eta_seconds: float | None = None
        self.queue_progress: float = 0.0
        self.queue_max_position: int = 0
        self.queue_rate: float = 0.0
        self.queue_prev_pos: int | None = None
        self.queue_prev_time: float = 0.0
        # Sell automation
        self.sell_active: bool = False
        self.sell_items: list = []        # [(item_id, name, qty), ...]
        self.sell_offset: int = 1
        self.sell_step: str = ""         # current step text for UI
        # Sell overlay visualization
        self.sell_match_rect: tuple | None = None   # (x, y, w, h) of last template match
        self.sell_match_name: str = ""               # template name for color coding
        self.sell_item_click: tuple | None = None    # (x, y) where item name was clicked
        # Marketplace
        self.marketplace_parsing: bool = False
        self.marketplace_total: int = 0
        self.marketplace_done: int = 0
        self.marketplace_error: str | None = None
        self.marketplace_start_time: float = 0.0
        # Price scan automation
        self.scan_active: bool = False
        self.scan_items: list = []     # [(item_id, name), ...]
        self.scan_step: str = ""       # current step text for UI
        # Server (for prices)
        self.current_server: str = "New York"
