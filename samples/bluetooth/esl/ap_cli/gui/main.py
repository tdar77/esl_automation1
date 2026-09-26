"""ESL AP activity monitor. Run with --demo to explore without hardware."""
import argparse
import csv
import json
import sys
import time
from collections import deque
from datetime import datetime, timezone

from PySide6.QtCore import QIODevice, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QTextCursor
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget)

from protocol import ANSI, SnapshotParser, demo_snapshot


class Trend(QWidget):
    """Bounded host history, plotted as cumulative accepted ping requests."""
    def __init__(self):
        super().__init__()
        self.points = deque(maxlen=300)
        self.setMinimumHeight(130)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#172330"))
        painter.setPen(QColor("#dce8f3"))
        painter.drawText(12, 22, "Accepted ping requests · total across logged tags · last 300 samples")
        if len(self.points) < 2:
            painter.drawText(12, 55, "Waiting for samples")
            return
        values = [p[1] for p in self.points]
        low, high = min(values), max(values)
        span = max(1, high - low)
        start, end = self.points[0][0], self.points[-1][0]
        previous = None
        painter.setPen(QPen(QColor("#56c8b5"), 2))
        for timestamp, value in self.points:
            x = 15 + int((timestamp - start) / max(.001, end - start) * (self.width() - 30))
            y = self.height() - 25 - int((value - low) / span * (self.height() - 65))
            if previous:
                painter.drawLine(*previous, x, y)
            previous = (x, y)
        painter.setPen(QColor("#dce8f3"))
        painter.drawText(12, self.height() - 6, f"{low}–{high} requests; this is not a delivery-rate chart")


class Monitor(QMainWindow):
    def __init__(self, demo=False):
        super().__init__()
        self.setWindowTitle("ESL AP Network Monitor" + (" — DEMO" if demo else ""))
        self.resize(1150, 800)
        self.demo = demo
        self.tick = 0
        self.parser = SnapshotParser()
        self.serial = QSerialPort(self)
        self.serial.readyRead.connect(self.receive)
        self.serial.errorOccurred.connect(self.serial_error)
        self.busy = None
        self.deadline = 0
        self.tail = ""
        self.snapshot = None
        self.last_received = None
        self.recording = None
        self.samples = deque(maxlen=10000)
        self.capture_id = 0
        self.faulted = False
        self.replay = False
        self.got_snapshot = False
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        row = QHBoxLayout()
        layout.addLayout(row)
        self.ports = QComboBox()
        self.ports.setEditable(True)
        row.addWidget(QLabel("Port"))
        row.addWidget(self.ports)
        self.button(row, "Rescan", self.scan_ports)
        self.baud = QSpinBox()
        self.baud.setRange(1200, 3000000)
        self.baud.setValue(115200)
        row.addWidget(QLabel("Baud"))
        row.addWidget(self.baud)
        self.connect_button = self.button(row, "Connect", self.toggle_connection)
        self.polling = QCheckBox("Auto refresh")
        self.polling.setChecked(True)
        row.addWidget(self.polling)
        self.interval = QSpinBox()
        self.interval.setRange(1, 60)
        self.interval.setValue(2)
        self.interval.setSuffix(" s")
        row.addWidget(self.interval)
        self.button(row, "Refresh now", self.poll)
        row.addStretch()

        self.status = QLabel("DEMO — synthetic data" if demo else "Disconnected")
        layout.addWidget(self.status)
        self.summary = QLabel("No snapshot yet")
        layout.addWidget(self.summary)
        note = QLabel("Activity log coverage: accepted requests and decoded GATT responses. "
                      "PAwR per-tag responses, RSSI, latency and delivery rate are not measured yet.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Group / ID (hex)", "Ping requests", "Request age (s)",
            "Image index", "GATT responses", "Response age (s)", "Coverage"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 2)
        self.trend = Trend()
        layout.addWidget(self.trend)

        controls = QHBoxLayout()
        layout.addLayout(controls)
        self.button(controls, "Initialize AP", lambda: self.send("esl_ap init"))
        self.button(controls, "Ping selected", self.ping_selected)
        self.tags = QSpinBox()
        self.tags.setRange(1, 32)
        self.tags.setValue(2)
        controls.addWidget(self.tags)
        self.button(controls, "Auto sync", lambda: self.send(f"esl_ap auto {self.tags.value()}"))
        self.button(controls, "Stop automation", lambda: self.send("esl_ap auto_stop"))
        self.operation = QComboBox()
        self.operation.addItems(["start_scan", "stop_scan", "start_padv", "stop_padv", "adv_dev_list"])
        controls.addWidget(self.operation)
        self.button(controls, "Run", lambda: self.send("esl_ap " + self.operation.currentText()))

        files = QHBoxLayout()
        layout.addLayout(files)
        self.record_button = self.button(files, "Record session", self.toggle_recording)
        self.button(files, "Export CSV", self.export_csv)
        self.button(files, "Replay session", self.load_replay)
        files.addStretch()
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.document().setMaximumBlockCount(2000)
        layout.addWidget(self.console, 1)
        self.scan_ports()
        if demo:
            self.connect_button.setEnabled(False)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.service)
        self.timer.start(100)
        self.next_poll = 0

    @staticmethod
    def button(row, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        row.addWidget(button)
        return button

    def scan_ports(self):
        current = self.ports.currentText()
        self.ports.clear()
        self.ports.addItems([port.portName() for port in QSerialPortInfo.availablePorts()])
        if current:
            self.ports.setCurrentText(current)

    def toggle_connection(self):
        if self.serial.isOpen():
            self.serial.close()
            self.connect_button.setText("Connect")
            self.busy = None
            self.status.setText("Disconnected — displayed data is historical")
            return
        self.serial.setPortName(self.ports.currentText().strip())
        self.serial.setBaudRate(self.baud.value())
        if not self.serial.open(QIODevice.OpenModeFlag.ReadWrite):
            self.status.setText(self.serial.errorString())
            return
        self.replay = False
        self.faulted = False
        self.capture_id += 1
        self.parser = SnapshotParser()
        self.tail = ""
        self.trend.points.clear()
        self.snapshot = None
        self.last_received = None
        self.table.setRowCount(0)
        self.connect_button.setText("Disconnect")
        self.status.setText("Connected — synchronizing with shell")
        self.send("")

    def serial_error(self, error):
        if error == QSerialPort.SerialPortError.ResourceError:
            self.serial.close()
            self.busy = None
            self.faulted = True
            self.connect_button.setText("Connect")
            self.status.setText("Serial connection lost — reconnect to resume")

    def send(self, command):
        if self.demo or self.replay or not self.serial.isOpen() or self.faulted:
            self.console.appendPlainText("Command unavailable: connect to a live AP first.")
            return
        if self.busy is not None:
            self.console.appendPlainText("AP shell is busy; wait for the current command.")
            return
        self.tail = ""
        self.busy = command
        if command == "esl_ap log json":
            self.got_snapshot = False
            self.parser.cancel()
        self.deadline = time.monotonic() + 10
        self.serial.write((command + "\r\n").encode("ascii"))
        self.status.setText("Waiting for shell: " + (command or "synchronize"))

    def receive(self):
        data = bytes(self.serial.readAll())
        self.write_record({"kind": "raw", "hex": data.hex()})
        text = data.decode("utf-8", errors="replace")
        self.console.moveCursor(QTextCursor.MoveOperation.End)
        self.console.insertPlainText(ANSI.sub("", text))
        self.tail = (self.tail + text)[-4096:]
        for snapshot in self.parser.feed(data):
            self.got_snapshot = True
            self.show_snapshot(snapshot)
        # The default Zephyr UART shell prompt terminates a command. The JSON
        # end marker alone does not mean the shell is ready for another command.
        if ANSI.sub("", self.tail).rstrip().endswith(":~$"):
            if self.busy == "esl_ap log json" and not self.got_snapshot:
                self.parser.cancel()
                self.faulted = True
                self.status.setText("No valid telemetry — check firmware supports 'esl_ap log json'; reconnect to retry")
            else:
                self.status.setText("Shell ready — operation results appear in console")
            self.busy = None

    def poll(self):
        if self.replay:
            return
        if self.demo:
            self.tick += 1
            self.show_snapshot(demo_snapshot(self.tick))
        elif self.serial.isOpen() and self.busy is None and not self.faulted:
            self.send("esl_ap log json")

    def service(self):
        now = time.monotonic()
        if self.busy is not None and now > self.deadline:
            self.busy = None
            self.faulted = True
            self.parser.cancel()
            self.status.setText("Shell timeout — reconnect to resume; check port, baud and firmware")
        if now >= self.next_poll:
            self.next_poll = now + self.interval.value()
            if self.polling.isChecked():
                self.poll()
        if self.last_received is not None and self.snapshot:
            age = now - self.last_received
            stale = age > max(5, 3 * self.interval.value())
            source = "REPLAY" if self.replay else "DEMO" if self.demo else "LIVE" if self.serial.isOpen() else "DISCONNECTED"
            self.summary.setText(f"{source} | Logged tags: {self.snapshot['count']} / {self.snapshot['capacity']} | "
                f"Dropped updates: {self.snapshot['dropped']} | Snapshot age: {age:.1f}s"
                + (" — STALE" if stale else "") + f" | Parser errors: {self.parser.errors}")

    def show_snapshot(self, snapshot, received=None, record=True):
        if self.snapshot and (snapshot["session"] != self.snapshot["session"] or
                              snapshot["uptime_ms"] < self.snapshot["uptime_ms"]):
            self.trend.points.clear()
            self.console.appendPlainText("AP session/time changed; chart restarted.")
        selected = self.table.item(self.table.currentRow(), 0)
        selected_key = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self.snapshot = snapshot
        self.last_received = time.monotonic()
        received = received or datetime.now(timezone.utc).isoformat()
        self.samples.append({"received": received, "capture": self.capture_id, "snapshot": snapshot,
                             "source": "replay" if self.replay else "demo" if self.demo else "serial"})
        if record:
            self.write_record({"kind": "snapshot", "snapshot": snapshot, "received": received})
        self.table.setRowCount(len(snapshot["tags"]))
        for index, tag in enumerate(sorted(snapshot["tags"], key=lambda t: (t["group"], t["tag"]))):
            age = lambda value: "Never" if value is None else f"{value / 1000:.2f}"
            values = [f"{tag['group']:02X} / {tag['tag']:02X}", tag["ping_requests"],
                      age(tag["ping_age_ms"]), "None" if tag["image"] is None else tag["image"],
                      tag["gatt_responses"], age(tag["gatt_response_age_ms"]), "GATT only"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, (tag["group"], tag["tag"]))
                self.table.setItem(index, column, item)
            if selected_key == (tag["group"], tag["tag"]):
                self.table.selectRow(index)
        self.trend.points.append((snapshot["uptime_ms"] / 1000, sum(t["ping_requests"] for t in snapshot["tags"])))
        self.trend.update()

    def ping_selected(self):
        item = self.table.item(self.table.currentRow(), 0)
        if item:
            group, tag = item.data(Qt.ItemDataRole.UserRole)
            self.send(f"esl_ap ping {group:02X} {tag:02X}")

    def write_record(self, record):
        if self.recording:
            try:
                self.recording.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(), **record}) + "\n")
                self.recording.flush()
            except OSError as exc:
                self.recording.close()
                self.recording = None
                self.record_button.setText("Record session")
                self.status.setText(f"Recording failed: {exc}")

    def toggle_recording(self):
        if self.recording:
            self.recording.close()
            self.recording = None
            self.record_button.setText("Record session")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Record session", "esl-session.jsonl", "JSON Lines (*.jsonl)")
        if path:
            try:
                self.recording = open(path, "w", encoding="utf-8")
                self.record_button.setText("Stop recording")
                self.write_record({"kind": "session", "demo": self.demo, "capture": self.capture_id})
            except OSError as exc:
                QMessageBox.warning(self, "Recording failed", str(exc))

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export samples", "esl-metrics.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["host_time_utc", "source", "capture", "ap_session", "uptime_ms", "group_decimal", "tag_decimal",
                    "ping_requests", "ping_age_ms", "requested_image", "gatt_responses", "gatt_response_age_ms"])
                for sample in self.samples:
                    snap = sample["snapshot"]
                    for tag in snap["tags"]:
                        writer.writerow([sample["received"], sample["source"], sample["capture"], snap["session"], snap["uptime_ms"],
                            *[tag[k] for k in ("group", "tag", "ping_requests", "ping_age_ms", "image", "gatt_responses", "gatt_response_age_ms")]])
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def load_replay(self):
        if self.serial.isOpen() or self.recording:
            QMessageBox.information(self, "Replay", "Disconnect and stop recording before replaying a session.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Replay session", "", "JSON Lines (*.jsonl)")
        if not path:
            return
        try:
            # Validate through the wire parser instead of trusting stored dictionaries.
            snapshots = deque(maxlen=10000)
            with open(path, encoding="utf-8") as file:
                for line in file:
                    record = json.loads(line)
                    if record.get("kind") != "snapshot":
                        continue
                    snap = record["snapshot"]
                    parser = SnapshotParser()
                    wire = [snap, *snap["tags"], {"v": 1, "type": "end", "id": snap["id"], "count": snap["count"]}]
                    parsed = parser.feed("".join("@ESL " + json.dumps(r) + "\n" for r in wire).encode())
                    if len(parsed) != 1 or parser.errors:
                        raise ValueError("Invalid snapshot in recording")
                    snapshots.append((parsed[0], record.get("received", record.get("time"))))
            if not snapshots:
                raise ValueError("No snapshots in recording")
            self.replay = True
            self.snapshot = None
            self.samples.clear()
            self.trend.points.clear()
            for snap, received in snapshots:
                self.show_snapshot(snap, received, record=False)
            self.status.setText(f"Replay loaded: {len(snapshots)} snapshots; chart shows last 300")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Replay failed", str(exc))

    def closeEvent(self, event):
        self.serial.close()
        if self.recording:
            self.recording.close()
        event.accept()


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("--demo", action="store_true")
    options = args.parse_args()
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    window = Monitor(options.demo)
    window.show()
    sys.exit(app.exec())
