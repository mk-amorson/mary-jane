"""Click sound system — app-wide event filter."""

import os

from PyQt5.QtWidgets import QPushButton, QLineEdit
from PyQt5.QtCore import Qt, QUrl, QObject, QEvent
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

from utils import resource_path

_SOUND_DIR = resource_path("sounds")
_CLICK_SOUND = os.path.join(_SOUND_DIR, "click.mp3")
_click_player: QMediaPlayer | None = None


def init_click_sound():
    global _click_player
    if _click_player is not None:
        return
    _click_player = QMediaPlayer()
    _click_player.setVolume(70)


def play_click():
    if _click_player is None:
        init_click_sound()
    _click_player.stop()
    _click_player.setMedia(QMediaContent(QUrl.fromLocalFile(_CLICK_SOUND)))
    _click_player.play()


_CLICK_TYPES = (QPushButton, QLineEdit)


class ClickSoundFilter(QObject):
    """App-wide event filter that plays click sound on interactive widgets."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if isinstance(obj, _CLICK_TYPES):
                play_click()
            elif type(obj).__name__ in ("ToggleSwitch", "TitleButton"):
                play_click()
        return False
