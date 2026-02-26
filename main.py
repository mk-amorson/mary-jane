import sys
import asyncio
import threading
import logging

from PyQt5.QtWidgets import QApplication

from core import AppState, SERVER_URL
from auth.token_store import TokenStore
from api_client import ApiClient
from modules.queue_monitor import queue_monitor_loop
from modules.fishing import fishing_bot_loop
from modules.subscription import SubscriptionManager
from ui.window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)


async def _fetch_bot_username(state):
    """Fetch bot_username from server once at startup."""
    try:
        data = await state.api_client.get_app_version()
        if data and data.get("bot_username"):
            state.bot_username = data["bot_username"]
            log.info("Bot username: @%s", state.bot_username)
    except Exception:
        log.debug("Failed to fetch bot_username", exc_info=True)


async def auth_check_loop(state):
    """Periodically check auth status, refresh user info and subscriptions."""
    # Initial refresh immediately on startup
    await asyncio.sleep(1)
    if state.token_store and state.token_store.is_authenticated:
        try:
            me = await state.api_client.get_me()
            if me:
                state.user_info = me.get("user")
                state.is_authenticated = True
                if state.subscription_manager:
                    await state.subscription_manager.refresh()
        except Exception:
            pass
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

    loop.create_task(_fetch_bot_username(state))
    loop.create_task(queue_monitor_loop(state))
    loop.create_task(fishing_bot_loop(state))
    loop.create_task(auth_check_loop(state))
    loop.run_forever()


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

    bg = threading.Thread(target=run_async_loop, args=(state,), daemon=True)
    bg.start()

    window = MainWindow(state)
    window.show()
    sys.exit(app.exec_())
