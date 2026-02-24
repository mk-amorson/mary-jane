import re
import logging
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

log = logging.getLogger(__name__)

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _normalize(text):
    t = text.lower().strip().replace("\u0451", "\u0435")
    return t


def _preprocess(img: Image.Image) -> Image.Image:
    """Enhance image for better OCR on game UI text."""
    gray = img.convert("L")
    enhanced = ImageEnhance.Contrast(gray).enhance(2.0)
    enhanced = enhanced.filter(ImageFilter.SHARPEN)
    return enhanced


def detect_items(frame: Image.Image, db_items: list[tuple[int, str]],
                 callback=None) -> list[tuple[int, str, int]]:
    w, h = frame.size

    # 1. Crop content zone
    x1 = int(w * 0.12)
    x2 = int(w * 0.85)
    y1 = int(h * 0.04)
    y2 = int(h * 0.95)
    crop = frame.crop((x1, y1, x2, y2))
    cw, ch = crop.size

    # 2. Preprocess
    processed = _preprocess(crop)

    # DEBUG: save crops
    import os
    _dbg = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "debug_sell")
    os.makedirs(_dbg, exist_ok=True)
    crop.save(os.path.join(_dbg, "crop_raw.png"))
    processed.save(os.path.join(_dbg, "crop_processed.png"))

    # 3. OCR
    try:
        data = pytesseract.image_to_data(
            processed, lang="rus+eng", output_type=pytesseract.Output.DICT,
            config="--oem 3 --psm 6",
        )
    except Exception:
        log.exception("pytesseract.image_to_data failed")
        return []

    # Collect words with positions
    words = []
    n = len(data["text"])
    for i in range(n):
        text = data["text"][i].strip()
        if not text:
            continue
        conf = int(data["conf"][i]) if str(data["conf"][i]) != "-1" else 0
        if conf < 15:
            continue
        x = data["left"][i]
        y = data["top"][i]
        bw = data["width"][i]
        bh = data["height"][i]
        x_center = x + bw / 2
        y_center = y + bh / 2
        words.append((text, x, y, bw, bh, x_center, y_center, conf))

    log.info("Sell OCR: %d words, crop %dx%d", len(words), cw, ch)

    # 4. Group into lines by y_center proximity (±20px)
    words.sort(key=lambda wrd: wrd[6])
    lines = []
    for word in words:
        placed = False
        for line in lines:
            avg_y = sum(w[6] for w in line) / len(line)
            if abs(avg_y - word[6]) <= 20:
                line.append(word)
                placed = True
                break
        if not placed:
            lines.append([word])

    for line in lines:
        line.sort(key=lambda wrd: wrd[5])

    # 5. Split lines into groups by x-gap
    #    Cards are spaced apart — big x-gaps mean separate cards
    MIN_GAP = cw * 0.05  # 5% of crop width = gap between cards
    groups = []  # each group: list of words, with avg x_center and y_center
    for line in lines:
        if not line:
            continue
        current_group = [line[0]]
        for wrd in line[1:]:
            prev = current_group[-1]
            # gap = left edge of current word - right edge of previous word
            gap = wrd[1] - (prev[1] + prev[3])
            if gap > MIN_GAP:
                groups.append(current_group)
                current_group = [wrd]
            else:
                current_group.append(wrd)
        groups.append(current_group)

    log.info("Sell OCR: %d groups after x-gap split", len(groups))
    for gi, g in enumerate(groups):
        text = " ".join(w[0] for w in g)
        avg_x = sum(w[5] for w in g) / len(g)
        avg_y = sum(w[6] for w in g) / len(g)
        log.info("  group %d: '%s' at (%.0f, %.0f)", gi, text, avg_x, avg_y)

    # 6. Find quantities — a group containing a number (possibly followed by mangled "шт")
    #    Tesseract reads "шт." as "wr.", "ur.", "un," etc.
    #    Strategy: find groups where there's a number ≥ 1
    quantities = []  # (qty, x_center, y_center)
    _num_re = re.compile(r"^\d+$")
    for g in groups:
        for idx, word in enumerate(g):
            if _num_re.match(word[0]):
                num = int(word[0])
                if num < 1:
                    continue
                # Real qty groups have an icon before the number (e.g. "× 2893 шт.")
                # Reject if number is the very first word (likely OCR noise)
                if idx == 0 and len(g) > 1:
                    continue
                is_qty = False
                if idx + 1 < len(g):
                    suffix = g[idx + 1][0]
                    if len(suffix) <= 4:
                        is_qty = True
                if not is_qty and len(g) <= 4 and sum(len(w[0]) for w in g) <= 15:
                    is_qty = True
                if is_qty:
                    avg_x = sum(w[5] for w in g) / len(g)
                    avg_y = sum(w[6] for w in g) / len(g)
                    quantities.append((num, avg_x, avg_y))
                    break

    log.info("Sell OCR: %d quantities found", len(quantities))
    for q in quantities:
        log.info("  qty: %d at (%.0f, %.0f)", q[0], q[1], q[2])

    # 7. Find names — match DB items in group text
    db_sorted = sorted(db_items, key=lambda item: len(item[1]), reverse=True)
    db_normalized = [(iid, name, _normalize(name)) for iid, name in db_sorted
                     if len(name) >= 2]

    found_names = []  # (item_id, name, x_center, y_center)
    used_groups = set()

    for gi, g in enumerate(groups):
        if gi in used_groups:
            continue
        group_text = " ".join(w[0] for w in g)
        norm_text = _normalize(group_text)
        for iid, name, norm_name in db_normalized:
            if norm_name in norm_text:
                avg_x = sum(w[5] for w in g) / len(g)
                avg_y = sum(w[6] for w in g) / len(g)
                found_names.append((iid, name, avg_x, avg_y))
                used_groups.add(gi)
                log.info("Sell OCR: matched '%s' in group '%s'", name, group_text)
                break

    log.info("Sell OCR: %d names matched", len(found_names))

    # 8. Match names with quantities — closest by x-distance, must be ABOVE
    results = []
    used_qty = set()

    for iid, name, nx, ny in found_names:
        best_qty = None
        best_dx = float("inf")
        for qi, (qty, qx, qy) in enumerate(quantities):
            if qi in used_qty:
                continue
            # quantity must be above the name
            if qy >= ny:
                continue
            dx = abs(qx - nx)
            if dx < best_dx:
                best_dx = dx
                best_qty = (qi, qty)

        qty_val = 0
        if best_qty is not None:
            used_qty.add(best_qty[0])
            qty_val = best_qty[1]
        results.append((iid, name, qty_val))

        if callback:
            callback(iid, name, qty_val)

    # 9. Deduplicate by item_id
    seen = set()
    deduped = []
    for iid, name, qty in results:
        if iid not in seen:
            seen.add(iid)
            deduped.append((iid, name, qty))

    return deduped
