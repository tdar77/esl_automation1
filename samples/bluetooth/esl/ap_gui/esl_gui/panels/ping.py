"""Tags tab: table of synced tags and the ping command."""

from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                             QLabel, QPushButton, QSpinBox, QTableView,
                             QVBoxLayout, QWidget)

from .. import commands
from ..controller import EslApController


class PingPanel(QWidget):
    TITLE = "Tags / Ping"

    def __init__(self, controller: EslApController) -> None:
        super().__init__()
        self.controller = controller

        self.table = QTableView()
        self.table.setModel(controller.tags)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setToolTip("Double-click a tag to ping it")

        self.ping_selected_btn = QPushButton("Ping selected")

        # Manual address entry covers tags synced before the GUI was attached
        # (the AP has no command that lists synced tags yet).
        self.group = QSpinBox()
        self.group.setRange(0, commands.GROUP_ID_MAX)
        self.esl = QSpinBox()
        self.esl.setRange(0, commands.ESL_ID_MAX)
        self.ping_addr_btn = QPushButton("Ping address")

        selected_row = QHBoxLayout()
        selected_row.addWidget(self.ping_selected_btn)
        selected_row.addStretch()
        selected_row.addWidget(QLabel("Group:"))
        selected_row.addWidget(self.group)
        selected_row.addWidget(QLabel("ESL ID:"))
        selected_row.addWidget(self.esl)
        selected_row.addWidget(self.ping_addr_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(selected_row)

        self.ping_selected_btn.clicked.connect(self._ping_selected)
        self.ping_addr_btn.clicked.connect(
            lambda: controller.ping(self.group.value(), self.esl.value()))
        self.table.doubleClicked.connect(lambda index: self._ping_row(index.row()))
        controller.connection_changed.connect(self._refresh_buttons)
        self._refresh_buttons()

    def _refresh_buttons(self, *_):
        connected = self.controller.is_connected()
        self.ping_selected_btn.setEnabled(connected)
        self.ping_addr_btn.setEnabled(connected)

    def _ping_selected(self) -> None:
        for index in self.table.selectionModel().selectedRows():
            self._ping_row(index.row())

    def _ping_row(self, row: int) -> None:
        tag = self.controller.tags.tag_at(row)
        self.controller.ping(tag.group, tag.esl)
