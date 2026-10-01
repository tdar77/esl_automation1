"""Line-oriented serial transport to the AP's Zephyr shell."""

import re
import sys

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtSerialPort import QSerialPort, QSerialPortInfo

from .parser import clean_line


class SerialLink(QObject):
    """Owns the QSerialPort; emits one cleaned line at a time.

    QSerialPort is event driven on the Qt main loop, so no worker thread is
    needed and all signals arrive on the GUI thread.
    """

    line_received = pyqtSignal(str)
    connection_changed = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._port = QSerialPort(self)
        self._port.readyRead.connect(self._on_ready_read)
        self._port.errorOccurred.connect(self._on_error)
        self._buffer = bytearray()

    @staticmethod
    def available_ports() -> list[tuple[str, str]]:
        """(name, description) pairs, e.g. ("COM5", "XDS110 Class Application/User UART").

        Names are what users type: COM3 on Windows, /dev/ttyACM0 elsewhere.
        Sorted naturally so COM10 comes after COM9.
        """
        ports = []
        for info in QSerialPortInfo.availablePorts():
            # On Windows systemLocation() is \\.\COM3; setPortName() takes COM3.
            name = info.portName() if sys.platform == "win32" else info.systemLocation()
            ports.append((name, info.description()))
        return sorted(ports, key=lambda p: [int(t) if t.isdigit() else t
                                            for t in re.split(r"(\d+)", p[0])])

    def is_open(self) -> bool:
        return self._port.isOpen()

    def open(self, port: str, baud: int) -> bool:
        self.close()
        self._port.setPortName(port)
        self._port.setBaudRate(baud)
        if not self._port.open(QSerialPort.OpenModeFlag.ReadWrite):
            self.error.emit(f"Cannot open {port}: {self._port.errorString()}")
            return False
        self._buffer.clear()
        self.connection_changed.emit(True)
        return True

    def close(self) -> None:
        if self._port.isOpen():
            self._port.close()
            self.connection_changed.emit(False)

    def send_line(self, text: str) -> bool:
        """Send one shell command. The shell collapses CRLF into one Enter."""
        if not self._port.isOpen():
            return False
        self._port.write((text + "\r\n").encode())
        return True

    def _on_ready_read(self) -> None:
        self._buffer += bytes(self._port.readAll())
        while (end := self._buffer.find(b"\n")) >= 0:
            raw = bytes(self._buffer[:end])
            del self._buffer[:end + 1]
            line = clean_line(raw.decode("utf-8", errors="replace"))
            if line.strip():
                self.line_received.emit(line)

    def _on_error(self, err: QSerialPort.SerialPortError) -> None:
        if err == QSerialPort.SerialPortError.NoError:
            return
        self.error.emit(self._port.errorString())
        if err in (QSerialPort.SerialPortError.ResourceError,
                   QSerialPort.SerialPortError.PermissionError):
            # Board unplugged or reset over USB (ResourceError on Linux,
            # often PermissionError on Windows): the handle is dead.
            self.close()
