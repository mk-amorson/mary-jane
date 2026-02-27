import re
import asyncio
import logging
import time
import winsound

import pytesseract
from PIL import Image

from core import get_game_rect

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

log = logging.getLogger(__name__)

POLL_INTERVAL = 1


def find_text_region(img: Image.Image):
    data = pytesseract.image_to_data(img, lang="rus+eng", output_type=pytesseract.Output.DICT)
    n = len(data["text"])
    texts = [data["text"][i].strip().lower() for i in range(n)]

    anchor_idx = None
    for i in range(n):
        if "очеред" in texts[i]:
            anchor_idx = i
            break
    if anchor_idx is None:
        return None

    phrase_start = anchor_idx
    for i in range(max(0, anchor_idx - 6), anchor_idx):
        if texts[i] and any(kw in texts[i] for kw in ("ваша", "позиц")):
            phrase_start = i
            break

    valid = [i for i in range(phrase_start, anchor_idx + 1)
             if texts[i] and data["width"][i] > 0]
    if not valid:
        return None

    tx = min(data["left"][i] for i in valid)
    ty = min(data["top"][i] for i in valid)
    tx2 = max(data["left"][i] + data["width"][i] for i in valid)
    ty2 = max(data["top"][i] + data["height"][i] for i in valid)
    return (tx, ty, tx2 - tx, ty2 - ty)


def calc_number_region(text_bbox, img_size):
    tx, ty, tw, th = text_bbox
    iw, ih = img_size

    nx = tx + tw
    nw = max(tw // 2, 30)
    expand = th * 0.5
    ny = int(ty - expand)
    nh = int(th + expand * 2)

    nx = max(0, nx)
    ny = max(0, ny)
    nw = min(nw, iw - nx)
    nh = min(nh, ih - ny)
    return (nx, ny, nw, nh)


def ocr_digits(img_crop: Image.Image) -> int | None:
    gray = img_crop.convert("L")
    text = pytesseract.image_to_string(
        gray,
        lang="eng",
        config="--psm 7 -c tessedit_char_whitelist=0123456789",
    ).strip()
    cleaned = re.sub(r"[^0-9]", "", text)
    if cleaned:
        return int(cleaned)
    return None


def _reset_ocr(state):
    state.queue_position = None
    state.ocr_text_region = None
    state.ocr_number_region = None
    state.ocr_text_locked = False
    _reset_eta(state)


_MAX_JUMP = 30       # max plausible change between consecutive readings
_EMA_ALPHA = 0.15    # exponential moving average smoothing factor


def _reset_eta(state):
    state.queue_eta_seconds = None
    state.queue_progress = 0.0
    state.queue_max_position = 0
    state.queue_rate = 0.0
    state.queue_prev_pos = None
    state.queue_prev_time = 0.0


def _update_eta(state, number):
    now = time.monotonic()

    # ── outlier filter: reject implausible jumps (OCR misread) ──
    if state.queue_prev_pos is not None:
        if abs(number - state.queue_prev_pos) > _MAX_JUMP:
            return

    # ── EMA rate ──
    if state.queue_prev_pos is not None:
        delta = state.queue_prev_pos - number
        dt = now - state.queue_prev_time
        if delta > 0 and dt > 0:
            instant_rate = delta / dt
            if state.queue_rate > 0:
                state.queue_rate = _EMA_ALPHA * instant_rate + (1 - _EMA_ALPHA) * state.queue_rate
            else:
                state.queue_rate = instant_rate

    state.queue_prev_pos = number
    state.queue_prev_time = now

    if number > state.queue_max_position:
        state.queue_max_position = number

    # ── ETA ──
    if state.queue_rate > 0:
        state.queue_eta_seconds = number / state.queue_rate
    else:
        state.queue_eta_seconds = None

    # ── progress ──
    if state.queue_max_position > 0:
        state.queue_progress = 1.0 - (number / state.queue_max_position)
    else:
        state.queue_progress = 0.0


def _beep_triple():
    """Play 3 short beeps via PC speaker."""
    for _ in range(3):
        winsound.Beep(1000, 200)
        winsound.Beep(37, 100)  # silence gap


async def queue_monitor_loop(state):
    log.info("Queue monitor loop started")
    notified = False

    while True:
        await asyncio.sleep(POLL_INTERVAL)

        if not state.queue_search_active:
            if state.ocr_text_locked:
                _reset_ocr(state)
                notified = False
            # stop WGC capture when not needed
            if state.frame_provider.running and not state.fishing_active and not state.fishing2_active:
                state.frame_provider.stop()
            continue

        # start WGC capture if not running
        if not state.frame_provider.running:
            state.frame_provider.start()

        try:
            state.game_rect = get_game_rect()
            img = state.frame_provider.get_image()
            if img is None:
                state.queue_position = None
                continue

            # Phase 1: find text once
            if not state.ocr_text_locked:
                text_bbox = find_text_region(img)
                if text_bbox is None:
                    log.debug("Queue text not found, retrying...")
                    continue
                state.ocr_text_region = text_bbox
                state.ocr_number_region = calc_number_region(text_bbox, img.size)
                state.ocr_text_locked = True
                log.info("Text locked at %s, number region: %s",
                         state.ocr_text_region, state.ocr_number_region)

            # Phase 2: OCR digits in small crop
            nr = state.ocr_number_region
            cropped = img.crop((nr[0], nr[1], nr[0] + nr[2], nr[1] + nr[3]))
            number = ocr_digits(cropped)
            state.queue_position = number

            if number is not None:
                _update_eta(state, number)
                log.info("Queue position: %d", number)
                thr = state.notify_threshold
                if thr > 0 and number < thr and not notified:
                    notified = True
                    # Notify via server API (sends to Telegram)
                    if state.api_client and state.is_authenticated:
                        try:
                            result = await state.api_client.notify_queue(number, thr)
                            if result:
                                log.info("Notification sent via server")
                            else:
                                _beep_triple()
                                log.info("Notification: beep (server notify failed)")
                        except Exception:
                            _beep_triple()
                            log.info("Notification: beep (server error)")
                    else:
                        _beep_triple()
                        log.info("Notification: triple beep (not authenticated)")
                if thr > 0 and number >= thr:
                    notified = False
            else:
                log.debug("Number not recognized in crop")

        except Exception:
            log.exception("Queue monitor error")
