"""Table model of the tags the GUI knows about."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt


@dataclass
class TagInfo:
    group: int
    esl: int
    synced_at: datetime | None = None
    pings_sent: int = 0
    last_ping: str = ""
    latency_s: float | None = None
    flags: dict[str, bool] = field(default_factory=dict)

    @property
    def address(self) -> str:
        return f"{self.group}:{self.esl}"


class TagTableModel(QAbstractTableModel):
    """One row per tag, sorted by (group, esl).

    To add a column: append to COLUMNS and return its value in _cell().
    """

    COLUMNS = ["Tag", "Group", "ESL ID", "Synced at", "Pings", "Last ping",
               "Latency", "State flags"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tags: list[TagInfo] = []

    # ------------------------------------------------------- Qt model API
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._tags)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        tag = self._tags[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._cell(tag, index.column())
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in (1, 2, 4, 6):
            return Qt.AlignmentFlag.AlignCenter
        return None

    @staticmethod
    def _cell(tag: TagInfo, column: int):
        match column:
            case 0:
                return tag.address
            case 1:
                return tag.group
            case 2:
                return tag.esl
            case 3:
                return tag.synced_at.strftime("%H:%M:%S") if tag.synced_at else "unknown"
            case 4:
                return tag.pings_sent
            case 5:
                return tag.last_ping
            case 6:
                return f"{tag.latency_s:.2f} s" if tag.latency_s is not None else ""
            case 7:
                return ", ".join(name for name, on in tag.flags.items() if on)
        return None

    # ------------------------------------------------------- Mutators
    def tag_at(self, row: int) -> TagInfo:
        return self._tags[row]

    def tags(self) -> list[TagInfo]:
        return list(self._tags)

    def ensure(self, group: int, esl: int) -> TagInfo:
        """Return the tag, inserting a row for it if it is new."""
        for row, tag in enumerate(self._tags):
            if (tag.group, tag.esl) == (group, esl):
                return tag
            if (tag.group, tag.esl) > (group, esl):
                break
        else:
            row = len(self._tags)
        tag = TagInfo(group, esl)
        self.beginInsertRows(QModelIndex(), row, row)
        self._tags.insert(row, tag)
        self.endInsertRows()
        return tag

    def update(self, group: int, esl: int, **changes) -> None:
        """Set TagInfo fields on a tag (creating it if needed) and refresh its row."""
        tag = self.ensure(group, esl)
        for name, value in changes.items():
            setattr(tag, name, value)
        self._row_changed(tag)

    def set_flag(self, group: int, esl: int, name: str, on: bool) -> None:
        tag = self.ensure(group, esl)
        tag.flags[name] = on
        self._row_changed(tag)

    def clear(self) -> None:
        self.beginResetModel()
        self._tags.clear()
        self.endResetModel()

    def _row_changed(self, tag: TagInfo) -> None:
        row = self._tags.index(tag)
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.COLUMNS) - 1))
