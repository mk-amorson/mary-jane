"""License activation dialog shown on first launch."""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)
from PyQt5.QtCore import Qt

from licensing import activate


class ActivationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mary Jane — Активация")
        self.setFixedSize(420, 200)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setStyleSheet(
            "QDialog { background: rgb(28, 28, 32); }"
            "QLabel { color: rgb(220, 220, 220); font-size: 14px; }"
            "QLineEdit {"
            "  background: rgb(38, 38, 44); color: rgb(240, 240, 240);"
            "  border: 1px solid rgba(255,255,255,20); border-radius: 5px;"
            "  padding: 8px; font-size: 14px;"
            "}"
            "QPushButton {"
            "  background: rgb(50, 50, 58); color: rgb(240, 240, 240);"
            "  border: 1px solid rgba(255,255,255,20); border-radius: 5px;"
            "  padding: 8px 16px; font-size: 14px;"
            "}"
            "QPushButton:hover { background: rgb(60, 60, 70); }"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        title = QLabel("Введите лицензионный ключ")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: rgb(240, 240, 240);")
        lay.addWidget(title)

        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX")
        lay.addWidget(self._key_input)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("font-size: 12px;")
        lay.addWidget(self._status)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._activate_btn = QPushButton("Активировать")
        self._activate_btn.setCursor(Qt.PointingHandCursor)
        self._activate_btn.clicked.connect(self._on_activate)
        btn_row.addWidget(self._activate_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

    def _on_activate(self):
        key = self._key_input.text().strip()
        if not key:
            self._status.setStyleSheet("font-size: 12px; color: rgb(220, 100, 100);")
            self._status.setText("Введите ключ")
            return

        self._activate_btn.setEnabled(False)
        self._status.setStyleSheet("font-size: 12px; color: rgb(180, 180, 180);")
        self._status.setText("Проверка...")
        self._status.repaint()

        ok, msg = activate(key)
        if ok:
            self._status.setStyleSheet("font-size: 12px; color: rgb(100, 200, 100);")
            self._status.setText(msg)
            self.accept()
        else:
            self._status.setStyleSheet("font-size: 12px; color: rgb(220, 100, 100);")
            self._status.setText(msg)
            self._activate_btn.setEnabled(True)
