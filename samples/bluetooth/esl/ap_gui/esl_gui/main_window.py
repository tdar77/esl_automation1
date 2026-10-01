"""Main window: connection toolbar, feature tabs, console."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QLabel, QMainWindow, QPushButton,
                             QSplitter, QTabWidget, QToolBar)

from .controller import EslApController
from .panels import PANELS
from .panels.console import ConsolePanel

BAUD_RATES = [115200, 230400, 460800, 921600, 9600]


class MainWindow(QMainWindow):
    def __init__(self, controller: EslApController) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("ESL AP Control")
        self.resize(1000, 750)

        self._build_toolbar()

        self.tabs = QTabWidget()
        for panel_cls in PANELS:
            self.tabs.addTab(panel_cls(controller), panel_cls.TITLE)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tabs)
        splitter.addWidget(ConsolePanel(controller))
        splitter.setSizes([420, 330])
        self.setCentralWidget(splitter)

        controller.connection_changed.connect(self._on_connection_changed)
        controller.notice.connect(lambda msg: self.statusBar().showMessage(msg, 8000))
        self._on_connection_changed(False)

    def _build_toolbar(self) -> None:
        bar = QToolBar("Connection")
        bar.setMovable(False)
        self.addToolBar(bar)

        self.port = QComboBox()
        self.port.setEditable(True)  # allow typing a path that is not enumerated
        self.port.setMinimumWidth(320)
        self.port.lineEdit().setPlaceholderText("COM3 or /dev/ttyACM0")
        refresh = QPushButton("↻")
        refresh.setToolTip("Rescan serial ports")
        self.baud = QComboBox()
        for rate in BAUD_RATES:
            self.baud.addItem(str(rate), rate)
        self.connect_btn = QPushButton("Connect")

        bar.addWidget(QLabel(" Port: "))
        bar.addWidget(self.port)
        bar.addWidget(refresh)
        bar.addWidget(QLabel("  Baud: "))
        bar.addWidget(self.baud)
        bar.addWidget(self.connect_btn)

        refresh.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self._toggle_connection)
        self.refresh_ports()

    def refresh_ports(self) -> None:
        current = self._selected_port()
        self.port.clear()
        for name, description in self.controller.link.available_ports():
            self.port.addItem(f"{name}  ({description})" if description else name, name)
        if current:
            index = self.port.findData(current)
            if index >= 0:
                self.port.setCurrentIndex(index)
            else:
                self.port.setCurrentText(current)

    def _selected_port(self) -> str:
        """Port name for the combo box, whether picked from the list or typed in."""
        text = self.port.currentText().strip()
        index = self.port.currentIndex()
        if index >= 0 and text == self.port.itemText(index):
            return self.port.itemData(index)
        return text

    def connect_to(self, port: str, baud: int) -> None:
        index = self.port.findData(port)
        if index >= 0:
            self.port.setCurrentIndex(index)
        else:
            self.port.setCurrentText(port)
        self.baud.setCurrentText(str(baud))
        self.controller.connect_port(port, baud)

    def _toggle_connection(self) -> None:
        if self.controller.is_connected():
            self.controller.disconnect_port()
        else:
            port = self._selected_port()
            if port:
                self.controller.connect_port(port, int(self.baud.currentText()))

    def _on_connection_changed(self, connected: bool) -> None:
        self.connect_btn.setText("Disconnect" if connected else "Connect")
        self.port.setEnabled(not connected)
        self.baud.setEnabled(not connected)
