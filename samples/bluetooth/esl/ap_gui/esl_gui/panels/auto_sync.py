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
        # One run fills one group, so a group's slots bound the count.
        self.count.setRange(1, commands.SLOTS_PER_GROUP)
        self.count.setValue(4)
        self.count.setToolTip("Number of additional tags to sync into the group. Tags "
                              "already synced are kept; new ones take the group's next "
                              "free ESL IDs.")
        self.group = QSpinBox()
        self.group.setRange(0, commands.GROUP_ID_MAX)
        self.group.setToolTip("Group to fill. The firmware rejects groups beyond its "
                              "configured group count.")
        self.slots_hint = QLabel()

        self.start_btn = QPushButton("Start auto sync")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip("Stops after the tag currently being synced finishes")

        self.status = QLabel("Idle")
        self.current = QLabel("–")
        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m tags")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.timing = QLabel("–")
        self.timing.setToolTip("Sync time: tag found -> connected, discovered, configured "
                               "and PAwR synced.\nScan time: AP scanning until the tag "
                               "was found.\nMeasured on console line arrival.")
        self._run_sync_times: list[float] = []

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Tags to sync:"))
        controls.addWidget(self.count)
        controls.addWidget(QLabel("Group:"))
        controls.addWidget(self.group)
        controls.addWidget(self.start_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch()

        hint_row = QHBoxLayout()
        hint_row.addWidget(self.slots_hint)
        hint_row.addStretch()

        state = QFormLayout()
        state.addRow("Status:", self.status)
        state.addRow("Current tag:", self.current)
        state.addRow("Progress:", self.progress)
        state.addRow("Sync time:", self.timing)
        box = QGroupBox("Automation state")
        box.setLayout(state)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addLayout(hint_row)
        layout.addWidget(box)
        layout.addStretch()

        self.start_btn.clicked.connect(
            lambda: controller.start_auto(self.count.value(), self.group.value()))
        self.group.valueChanged.connect(self._refresh_slots_hint)
        controller.tags.rowsInserted.connect(self._refresh_slots_hint)
        controller.tags.dataChanged.connect(self._refresh_slots_hint)
        controller.tags.modelReset.connect(self._refresh_slots_hint)
        controller.auto_group.connect(self.group.setValue)
        self.stop_btn.clicked.connect(controller.stop_auto)
        controller.connection_changed.connect(self._refresh_buttons)
        controller.auto_running_changed.connect(self._refresh_buttons)
        controller.auto_status_changed.connect(self.status.setText)
        controller.auto_current_tag.connect(lambda t: self.current.setText(t or "–"))
        controller.auto_progress.connect(self._on_progress)
        controller.auto_running_changed.connect(self._on_running_changed)
        controller.sync_timed.connect(self._on_sync_timed)
        self._refresh_buttons()
        self._refresh_slots_hint()

    def _refresh_buttons(self, *_):
        # Stop is always available when connected: auto_running is inferred
        # from console text and can be wrong (GUI attached mid-run, run started
        # from the console), and auto_stop is harmless when the AP is idle.
        connected = self.controller.is_connected()
        running = self.controller.auto_running
        self.start_btn.setEnabled(connected and not running)
        self.count.setEnabled(connected and not running)
        self.group.setEnabled(connected and not running)
        self.stop_btn.setEnabled(connected)

    def _on_progress(self, synced: int, target: int) -> None:
        self.progress.setRange(0, max(target, 1))
        self.progress.setValue(synced)

    def _on_running_changed(self, running: bool) -> None:
        if running:  # new run: averages are per run
            self._run_sync_times.clear()
            self.timing.setText("–")

    def _on_sync_timed(self, group: int, esl: int, scan_s, sync_s: float) -> None:
        self._run_sync_times.append(sync_s)
        times = self._run_sync_times
        scan = f" (scan {scan_s:.2f} s)" if scan_s is not None else ""
        self.timing.setText(
            f"last {group}:{esl}  {sync_s:.2f} s{scan}   ·   run avg {sum(times) / len(times):.2f} s, "
            f"min {min(times):.2f} s, max {max(times):.2f} s over {len(times)} tag(s)")

    def _refresh_slots_hint(self, *_) -> None:
        """Free slots in the chosen group, as far as the GUI has seen.

        Only an estimate: tags synced before the GUI connected are not
        counted. The firmware does the real check and rejects the run if
        the group is too full.
        """
        group = self.group.value()
        seen = sum(1 for tag in self.controller.tags.tags()
                   if tag.group == group and tag.synced_at is not None)
        free = max(commands.SLOTS_PER_GROUP - seen, 0)
        self.slots_hint.setText(
            f"Group {group}: {seen} synced tag(s) seen by the GUI, "
            f"~{free} of {commands.SLOTS_PER_GROUP} slots free")
