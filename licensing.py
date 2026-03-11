"""Hardware-bound license activation via Gumroad API."""

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import winreg

log = logging.getLogger(__name__)

# Gumroad product — set when product is created on Gumroad
GUMROAD_PRODUCT_ID = ""

# Dev key — bypasses Gumroad, activates locally
DEV_KEY = "MJ-DEV-2026"

# Offline tolerance: app works without internet for this many days
GRACE_PERIOD_DAYS = 30
# Re-validate license online every N days
REVALIDATION_DAYS = 7


def _config_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "config.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def get_hardware_id() -> str:
    """Deterministic hardware fingerprint (CPU + disk + Windows GUID)."""
    try:
        cpu = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Processor).ProcessorId"],
            text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        ).strip()
    except Exception:
        cpu = "unknown-cpu"

    try:
        disk = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_DiskDrive | Where-Object {$_.Index -eq 0}).SerialNumber"],
            text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        ).strip()
    except Exception:
        disk = "unknown-disk"

    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
        )
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
    except Exception:
        guid = "unknown-guid"

    raw = f"{cpu}|{disk}|{guid}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _validate_online(license_key: str) -> dict | None:
    """POST to Gumroad verify API. Returns product info dict or None."""
    data = urllib.parse.urlencode(
        {
            "product_id": GUMROAD_PRODUCT_ID,
            "license_key": license_key,
            "increment_uses_count": "true",
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.gumroad.com/v2/licenses/verify", data=data, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("success"):
            return result
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        log.warning("License validation request failed: %s", e)
    return None


def _load_config() -> dict:
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_config(data: dict):
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def check_activation() -> bool:
    """Check if app is activated on this machine (offline check)."""
    cfg = _load_config()
    act = cfg.get("activation")
    if not act:
        return False
    if act.get("hardware_id") != get_hardware_id():
        log.warning("Hardware mismatch — activation invalid")
        return False
    last_verified = act.get("last_verified", 0)
    days_since = (time.time() - last_verified) / 86400
    if days_since > GRACE_PERIOD_DAYS:
        log.warning("Grace period expired (%.0f days)", days_since)
        return False
    return True


def activate(license_key: str) -> tuple[bool, str]:
    """Validate key online, bind to hardware, store in config."""
    hw_id = get_hardware_id()

    # Dev key — skip Gumroad, activate locally
    if license_key.strip() == DEV_KEY:
        cfg = _load_config()
        cfg["activation"] = {
            "license_key": license_key.strip(),
            "hardware_id": hw_id,
            "activated_at": time.time(),
            "last_verified": time.time(),
        }
        _save_config(cfg)
        log.info("Dev license activated")
        return True, "Активация успешна (dev)"

    result = _validate_online(license_key)
    if result is None:
        return False, "Неверный ключ или ошибка сети"

    cfg = _load_config()
    cfg["activation"] = {
        "license_key": license_key,
        "hardware_id": hw_id,
        "activated_at": time.time(),
        "last_verified": time.time(),
    }
    _save_config(cfg)
    log.info("License activated successfully")
    return True, "Активация успешна"


def try_revalidate():
    """Silent periodic re-validation (every REVALIDATION_DAYS)."""
    cfg = _load_config()
    act = cfg.get("activation")
    if not act or not act.get("license_key"):
        return
    if act.get("license_key") == DEV_KEY:
        return
    days_since = (time.time() - act.get("last_verified", 0)) / 86400
    if days_since < REVALIDATION_DAYS:
        return
    log.info("Re-validating license (%.0f days since last check)", days_since)
    result = _validate_online(act["license_key"])
    if result:
        act["last_verified"] = time.time()
        cfg["activation"] = act
        _save_config(cfg)
        log.info("License re-validated successfully")
    else:
        log.warning("Re-validation failed, grace period continues")


def deactivate():
    """Clear activation data (for switching machines)."""
    cfg = _load_config()
    cfg.pop("activation", None)
    _save_config(cfg)
    log.info("License deactivated")
