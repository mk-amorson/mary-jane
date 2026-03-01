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
_DEFAULT_SERVER_URL = "https://axiomatic-aryana-hillocky.ngrok-free.dev"


def _load_server_url() -> str:
    import json, os, sys
    if getattr(sys, 'frozen', False):
        cfg_dir = os.path.dirname(sys.executable)
    else:
        cfg_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(cfg_dir, "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f).get("server_url", _DEFAULT_SERVER_URL)
    except (FileNotFoundError, json.JSONDecodeError):
        return _DEFAULT_SERVER_URL


SERVER_URL = _load_server_url()


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
        self._gen = 0

    @property
    def running(self):
        return self._running

    def start(self):
        if self._running:
            return
        # Stop lingering capture from previous session
        if self._control:
            try:
                self._control.stop()
            except Exception:
                pass
            self._control = None

        self._gen += 1
        gen = self._gen
        self._running = True
        log.info("GameFrameProvider starting (gen=%d)", gen)

        provider = self

        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            window_name=self._window_name,
        )

        @capture.event
        def on_frame_arrived(frame: Frame, capture_control: InternalCaptureControl):
            if provider._gen != gen:
                return
            arr = frame.frame_buffer.copy()
            with provider._lock:
                provider._frame = arr

        @capture.event
        def on_closed():
            if provider._gen != gen:
                log.debug("Ignoring stale on_closed (gen=%d, current=%d)", gen, provider._gen)
                return
            provider._running = False
            provider._frame = None
            provider._control = None
            log.info("GameFrameProvider stopped (gen=%d)", gen)

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
        # Stash
        self.stash_active: bool = False
        # WGC frame provider (single capture module)
        self.frame_provider: GameFrameProvider = GameFrameProvider(GAME_WINDOW_TITLE)
        # Fishing v2
        self.fishing2_active: bool = False
        self.fishing2_step: str = "idle"              # idle / cast / strike / reel / end
        self.fishing2_bar_rect: tuple | None = None
        self.fishing2_green_zone: tuple | None = None
        self.fishing2_slider_x: int | None = None
        self.fishing2_bobber_rect: tuple | None = None
        self.fishing2_bubbles: bool = False
        self.fishing2_camera_dir: str | None = None
        self.fishing2_take_icon: tuple | None = None
        self.fishing2_take_pause: float = 0.0
        self.fishing2_pred_x: int | None = None
        self.fishing2_slider_bounds: tuple | None = None  # (left, right)
        self.fishing2_pred_time: float = 0.12
        self.fishing2_debug: bool = False
        self.fishing2_calibrated: bool = False
        # Queue ETA (EMA-based)
        self.queue_eta_seconds: float | None = None
        self.queue_progress: float = 0.0
        self.queue_max_position: int = 0
        self.queue_rate: float = 0.0
        self.queue_prev_pos: int | None = None
        self.queue_prev_time: float = 0.0
        # Markers (memory-based)
        self.markers_active: bool = False
        self.markers_pos: tuple | None = None       # (x, y, z)
        self.markers_yaw: float | None = None       # entity heading (for arrow)
        self.markers_pitch: float | None = None     # entity pitch (None for now)
        self.markers_cam_yaw: float | None = None   # camera yaw (for labels)
        self.markers_cam_pitch: float | None = None # camera pitch (for labels)
        self.markers_cam_pos: tuple | None = None   # (x,y,z) camera position from viewport+0x100
        self.markers_cam_right: tuple | None = None # (x,y,z) camera right from viewport+0x50
        self.markers_cam_fwd: tuple | None = None   # (x,y,z) camera forward from viewport+0x60
        self.markers_cam_up: tuple | None = None    # (x,y,z) camera up from viewport+0x70
        self.markers_target: tuple | None = None    # (x, y, z) saved marker
