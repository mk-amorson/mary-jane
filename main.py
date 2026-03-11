import sys
import asyncio
import threading
import logging

from PyQt5.QtWidgets import QApplication

from core import AppState
from supabase_client import SupabaseClient
from licensing import check_activation, try_revalidate
from modules.queue import queue_monitor_loop
from modules.fishing import fishing2_bot_loop
from modules.markers import markers_loop
from modules.toilet import toilet_bot_loop
from ui.window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
# Fishing debug logs — shows timings for every detection + action
logging.getLogger("modules.fishing").setLevel(logging.DEBUG)
log = logging.getLogger(__name__)


def run_async_loop(state):
    """Run asyncio event loop in a background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    state.loop = loop

    loop.create_task(queue_monitor_loop(state))
    loop.create_task(fishing2_bot_loop(state))
    loop.create_task(toilet_bot_loop(state))
    loop.create_task(markers_loop(state))
    loop.run_forever()


if __name__ == "__main__":
    state = AppState()

    # License check
    if not check_activation():
        app = QApplication(sys.argv)
        from ui.activation import ActivationDialog
        dlg = ActivationDialog()
        if dlg.exec_() != ActivationDialog.Accepted:
            sys.exit(0)

    state.is_licensed = True
    state.supabase = SupabaseClient()
    try_revalidate()

    app = QApplication.instance() or QApplication(sys.argv)

    bg = threading.Thread(target=run_async_loop, args=(state,), daemon=True)
    bg.start()

    window = MainWindow(state)
    window.show()
    sys.exit(app.exec_())
