import sys
import os
import asyncio
import threading
import logging

from PyQt5.QtWidgets import QApplication, QMessageBox, QProgressDialog
from PyQt5.QtCore import Qt

from version import __version__
from core import AppState, SERVER_URL
from auth.token_store import TokenStore
from api_client import ApiClient
from modules.queue_monitor import queue_monitor_loop
from modules.fishing import fishing_bot_loop
from modules.sell.automation import sell_bot_loop
from modules.price_scan.automation import price_scan_loop
from modules.subscription import SubscriptionManager
from ui.window import MainWindow
from updater import check_update, download_update, apply_update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)


async def auth_check_loop(state):
    """Periodically check auth status, refresh user info and subscriptions."""
    while True:
        await asyncio.sleep(30)
        if state.token_store and state.token_store.is_authenticated:
            try:
                me = await state.api_client.get_me()
                if me:
                    state.user_info = me.get("user")
                    state.is_authenticated = True
                    # Refresh subscriptions
                    if state.subscription_manager:
                        await state.subscription_manager.refresh()
                else:
                    state.is_authenticated = False
                    state.user_info = None
            except Exception:
                pass
        else:
            state.is_authenticated = False
            state.user_info = None


def run_async_loop(state):
    """Run asyncio event loop in a background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    state.loop = loop

    loop.create_task(queue_monitor_loop(state))
    loop.create_task(fishing_bot_loop(state))
    loop.create_task(sell_bot_loop(state))
    loop.create_task(price_scan_loop(state))
    loop.create_task(auth_check_loop(state))
    loop.run_forever()


def _check_for_updates(api_client):
    """Run update check synchronously before showing main window."""
    if not getattr(sys, 'frozen', False):
        return  # skip in dev mode

    loop = asyncio.new_event_loop()
    try:
        update_info = loop.run_until_complete(check_update(api_client))
    except Exception:
        log.debug("Update check failed", exc_info=True)
        return
    finally:
        loop.close()

    if update_info is None:
        return

    version = update_info.get("version", "?")
    url = update_info.get("download_url", "")
    if not url:
        return

    reply = QMessageBox.question(
        None,
        "Обновление",
        f"Доступна новая версия {version}.\nТекущая: {__version__}\n\nОбновить?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if reply != QMessageBox.Yes:
        return

    current_exe = sys.executable
    new_exe = os.path.join(os.path.dirname(current_exe), "MJPort_new.exe")

    progress = QProgressDialog("Загрузка обновления...", "Отмена", 0, 100)
    progress.setWindowTitle("Обновление MJPort")
    progress.setWindowModality(Qt.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    def on_progress(pct):
        progress.setValue(int(pct * 100))

    dl_loop = asyncio.new_event_loop()
    try:
        ok = dl_loop.run_until_complete(download_update(url, new_exe, on_progress))
    except Exception:
        log.exception("Download failed")
        ok = False
    finally:
        dl_loop.close()

    progress.close()

    if ok and not progress.wasCanceled():
        apply_update(new_exe)
    elif not ok:
        QMessageBox.warning(None, "Ошибка", "Не удалось скачать обновление.")


if __name__ == "__main__":
    state = AppState()

    # Auth setup
    token_store = TokenStore()
    api_client = ApiClient(SERVER_URL, token_store)
    state.token_store = token_store
    state.api_client = api_client
    state.is_authenticated = token_store.is_authenticated

    # Subscription manager
    sub_manager = SubscriptionManager(state)
    state.subscription_manager = sub_manager

    app = QApplication(sys.argv)

    # Check for updates before starting background loop and UI
    _check_for_updates(api_client)

    bg = threading.Thread(target=run_async_loop, args=(state,), daemon=True)
    bg.start()

    window = MainWindow(state)
    window.show()
    sys.exit(app.exec_())
