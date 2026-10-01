"""Auto Sync tab: drive ``esl_ap auto <n>`` / ``esl_ap auto_stop``."""

from PyQt6.QtWidgets import (QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
                             QWidget)

from .. import commands
from ..controller import EslApController


class AutoSyncPanel(QWidget):
    TITLE = "Auto Sync"

    def __init__(self, controller: EslApController) -> None:
        super().__init__()
        self.controller = controller

        self.count = QSpinBox()
        self.count.setRange(1, commands.AUTO_MAX_COUNT)
        self.count.setValue(4)
        self.count.setToolTip("Number of additional tags to sync. Tags already "
                              "synced are kept; new ones take the next free IDs.")

        self.start_btn = QPushButton("Start auto sync")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip("Stops after the tag currently being synced finishes")

        self.status = QLabel("Idle")
        self.current = QLabel("–")
        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m tags")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Tags to sync:"))
        controls.addWidget(self.count)
        controls.addWidget(self.start_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch()

        state = QFormLayout()
        state.addRow("Status:", self.status)
        state.addRow("Current tag:", self.current)
        state.addRow("Progress:", self.progress)
        box = QGroupBox("Automation state")
        box.setLayout(state)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(box)
        layout.addStretch()

        self.start_btn.clicked.connect(lambda: controller.start_auto(self.count.value()))
        self.stop_btn.clicked.connect(controller.stop_auto)
        controller.connection_changed.connect(self._refresh_buttons)
        controller.auto_running_changed.connect(self._refresh_buttons)
        controller.auto_status_changed.connect(self.status.setText)
        controller.auto_current_tag.connect(lambda t: self.current.setText(t or "–"))
        controller.auto_progress.connect(self._on_progress)
        self._refresh_buttons()

    def _refresh_buttons(self, *_):
        # Stop is always available when connected: auto_running is inferred
        # from console text and can be wrong (GUI attached mid-run, run started
        # from the console), and auto_stop is harmless when the AP is idle.
        connected = self.controller.is_connected()
        running = self.controller.auto_running
        self.start_btn.setEnabled(connected and not running)
        self.count.setEnabled(connected and not running)
        self.stop_btn.setEnabled(connected)

    def _on_progress(self, synced: int, target: int) -> None:
        self.progress.setRange(0, max(target, 1))
        self.progress.setValue(synced)
