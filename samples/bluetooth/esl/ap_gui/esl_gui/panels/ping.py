"""Tags tab: table of synced tags and the ping command."""

from PyQt6.QtCore import QModelIndex, QSortFilterProxyModel
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout,
                             QHeaderView, QLabel, QPushButton, QSpinBox,
                             QTableView, QVBoxLayout, QWidget)

from .. import commands
from ..controller import EslApController
from ..tag_model import TagTableModel


class GroupFilterProxy(QSortFilterProxyModel):
    """Shows only the tags of one group, or all tags when group is None."""

    def __init__(self, source: TagTableModel) -> None:
        super().__init__()
        self.setSourceModel(source)
        self._group: int | None = None

    def set_group(self, group: int | None) -> None:
        self._group = group
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if self._group is None:
            return True
        return self.sourceModel().tag_at(source_row).group == self._group


class PingPanel(QWidget):
    TITLE = "Tags / Ping"

    def __init__(self, controller: EslApController) -> None:
        super().__init__()
        self.controller = controller

        # Group filter: rebuilt whenever tags are added or the list is cleared.
        self.group_filter = QComboBox()
        self.group_filter.setMinimumContentsLength(18)
        self.group_filter.setToolTip("Show only the tags of one group")
        self.shown = QLabel()

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Show:"))
        filter_row.addWidget(self.group_filter)
        filter_row.addWidget(self.shown)
        filter_row.addStretch()

        self.proxy = GroupFilterProxy(controller.tags)
        self.table = QTableView()
        self.table.setModel(self.proxy)
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
        layout.addLayout(filter_row)
        layout.addWidget(self.table)
        layout.addLayout(selected_row)

        self.group_filter.currentIndexChanged.connect(self._on_group_selected)
        self.ping_selected_btn.clicked.connect(self._ping_selected)
        self.ping_addr_btn.clicked.connect(
            lambda: controller.ping(self.group.value(), self.esl.value()))
        self.table.doubleClicked.connect(self._ping_index)
        controller.tags.rowsInserted.connect(self._refresh_groups)
        controller.tags.modelReset.connect(self._refresh_groups)
        controller.connection_changed.connect(self._refresh_buttons)
        self._refresh_groups()
        self._refresh_buttons()

    def _refresh_buttons(self, *_):
        connected = self.controller.is_connected()
        self.ping_selected_btn.setEnabled(connected)
        self.ping_addr_btn.setEnabled(connected)

    def _refresh_groups(self, *_) -> None:
        """Rebuild the dropdown from the current tags, keeping the selection."""
        tags = self.controller.tags.tags()
        counts: dict[int, int] = {}
        for tag in tags:
            counts[tag.group] = counts.get(tag.group, 0) + 1

        selected = self.group_filter.currentData()
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem(f"All groups ({len(tags)} tags)", None)
        for group in sorted(counts):
            self.group_filter.addItem(f"Group {group} ({counts[group]} tags)", group)
        index = self.group_filter.findData(selected) if selected is not None else 0
        # A selected group disappears only when the list is cleared (AP reboot).
        self.group_filter.setCurrentIndex(max(index, 0))
        self.group_filter.blockSignals(False)
        self._on_group_selected()

    def _on_group_selected(self, *_) -> None:
        group = self.group_filter.currentData()
        self.proxy.set_group(group)
        if group is not None:
            # Pre-fill manual ping so pinging inside the focused group is quick.
            self.group.setValue(group)
        self.shown.setText(f"{self.proxy.rowCount()} shown")

    def _ping_selected(self) -> None:
        for index in self.table.selectionModel().selectedRows():
            self._ping_index(index)

    def _ping_index(self, proxy_index: QModelIndex) -> None:
        # Table rows are proxy rows; map back to the full tag list.
        row = self.proxy.mapToSource(proxy_index).row()
        tag = self.controller.tags.tag_at(row)
        self.controller.ping(tag.group, tag.esl)
