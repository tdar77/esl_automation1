"""Headless GUI integration checks; requires PySide6."""
import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from main import Monitor
from protocol import demo_snapshot
from test_protocol import wire


class FakeSerial:
    def __init__(self, data):
        self.data = data

    def readAll(self):
        return self.data

    def close(self):
        pass


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = Monitor(True)
        self.window.timer.stop()

    def tearDown(self):
        self.window.close()

    def test_demo_and_session_reset(self):
        self.window.poll()
        self.window.poll()
        self.assertEqual(self.window.table.rowCount(), 2)
        self.assertEqual(len(self.window.trend.points), 2)
        snapshot = demo_snapshot(3)
        snapshot['session'] = 99
        self.window.show_snapshot(snapshot)
        self.assertEqual(len(self.window.trend.points), 1)

    def test_record_export_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            recording = str(Path(directory) / 'session.jsonl')
            export = str(Path(directory) / 'samples.csv')
            with patch('main.QFileDialog.getSaveFileName', return_value=(recording, '')):
                self.window.toggle_recording()
            self.window.poll()
            self.window.poll()
            self.window.toggle_recording()
            with patch('main.QFileDialog.getSaveFileName', return_value=(export, '')):
                self.window.export_csv()
            with open(export, newline='', encoding='utf-8') as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]['source'], 'demo')
            with patch('main.QFileDialog.getOpenFileName', return_value=(recording, '')):
                self.window.load_replay()
            self.assertTrue(self.window.replay)
            self.assertEqual(len(self.window.samples), 2)
            self.window.poll()
            self.assertEqual(len(self.window.samples), 2)

    def test_serial_snapshot_and_prompt(self):
        self.window.busy = 'esl_ap log json'
        self.window.serial = FakeSerial(wire(demo_snapshot(1)) + b'\x1b[32muart:~$ ')
        self.window.receive()
        self.assertIsNone(self.window.busy)
        self.assertEqual(self.window.snapshot['count'], 2)
        self.assertFalse(self.window.faulted)

    def test_missing_telemetry_stops_commands(self):
        self.window.busy = 'esl_ap log json'
        self.window.serial = FakeSerial(b'Unknown command\r\nuart:~$ ')
        self.window.receive()
        self.assertTrue(self.window.faulted)
        self.assertIsNone(self.window.snapshot)

    def test_ping_converts_ids_to_hex(self):
        snapshot = demo_snapshot(1)
        snapshot['tags'][0].update(group=16, tag=31)
        self.window.show_snapshot(snapshot)
        self.window.table.selectRow(1)
        with patch.object(self.window, 'send') as send:
            self.window.ping_selected()
            send.assert_called_once_with('esl_ap ping 10 1F')


if __name__ == '__main__':
    unittest.main()
