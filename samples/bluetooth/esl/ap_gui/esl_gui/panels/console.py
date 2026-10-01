"""Raw console: everything the AP prints, plus a free-form command line."""

from PyQt6.QtGui import QFontDatabase, QKeyEvent
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLineEdit, QPlainTextEdit,
                             QPushButton, QVBoxLayout, QWidget)

from ..controller import EslApController

MAX_LINES = 5000


class HistoryLineEdit(QLineEdit):
    """QLineEdit with Up/Down command history."""

    def __init__(self) -> None:
        super().__init__()
        self.history: list[str] = []
        self._pos = 0

    def remember(self, text: str) -> None:
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self._pos = len(self.history)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Up and self.history:
            self._pos = max(self._pos - 1, 0)
            self.setText(self.history[self._pos])
        elif event.key() == Qt.Key.Key_Down and self.history:
            self._pos = min(self._pos + 1, len(self.history))
            self.setText(self.history[self._pos] if self._pos < len(self.history) else "")
        else:
            super().keyPressEvent(event)


class ConsolePanel(QWidget):
    def __init__(self, controller: EslApController) -> None:
        super().__init__()
        self.controller = controller

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(MAX_LINES)
        self.view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        self.input = HistoryLineEdit()
        self.input.setPlaceholderText("Shell command, e.g. esl_ap log")
        send_btn = QPushButton("Send")
        clear_btn = QPushButton("Clear")

        row = QHBoxLayout()
        row.addWidget(self.input)
        row.addWidget(send_btn)
        row.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        layout.addLayout(row)

        self.input.returnPressed.connect(self._send)
        send_btn.clicked.connect(self._send)
        clear_btn.clicked.connect(self.view.clear)
        controller.line_received.connect(self.view.appendPlainText)

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.remember(text)
        self.input.clear()
        self.controller.send_command(text)
