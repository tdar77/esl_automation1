"""Controller tests: replay console lines without a serial port.

Needs PyQt6 (skipped otherwise). Runs headless via QT_QPA_PLATFORM=offscreen.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QCoreApplication
    from esl_gui import controller as ctl
except ImportError:  # pragma: no cover
    ctl = None


@unittest.skipIf(ctl is None, "PyQt6 not installed")
class ControllerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.c = ctl.EslApController()
        self.sent = []
        # Pretend to be connected and capture what would go to the UART.
        self.c.link.is_open = lambda: True
        self.c.link.send_line = lambda text: self.sent.append(text) or True

    def feed(self, *lines):
        for line in lines:
            self.c._on_line(line)

    def tag(self, group, esl):
        return next(t for t in self.c.tags.tags() if (t.group, t.esl) == (group, esl))

    def test_auto_run_populates_tags(self):
        progress, status = [], []
        self.c.auto_progress.connect(lambda s, t: progress.append((s, t)))
        self.c.auto_status_changed.connect(status.append)

        self.c.start_auto(2)
        self.assertEqual(self.sent, ["esl_ap auto 2"])
        self.feed("ESL AP automation started",
                  "[APPL_AUTO]: ESL tag [0:0] added, connecting",
                  "[APPL]: ESL tag [0 : 0] synchronized (status 0x0000)",
                  "[APPL_AUTO]: 1/2 tags synced",
                  "[APPL]: ESL tag [0 : 1] synchronized (status 0x0000)",
                  "[APPL_AUTO]: 2/2 tags synced",
                  "[APPL_AUTO]: batch finished - synced tags retained")

        self.assertEqual([t.address for t in self.c.tags.tags()], ["0:0", "0:1"])
        self.assertEqual(progress[-1], (2, 2))
        self.assertEqual(status[-1], "Done")
        self.assertFalse(self.c.auto_running)

    def test_failed_sync_is_not_listed(self):
        self.feed("[APPL]: ESL tag [0 : 0] synchronized (status 0x0101)")
        self.assertEqual(self.c.tags.rowCount(), 0)

    def test_auto_error_aborts(self):
        self.feed("ESL AP automation started", "[APPL_AUTO]: tag disconnected before sync")
        self.assertFalse(self.c.auto_running)

    def test_ping_response_correlated_by_group(self):
        self.c.ping(0, 10)
        self.assertEqual(self.sent, ["esl_ap ping 0 a"])
        self.assertEqual(self.tag(0, 10).last_ping, "waiting…")

        self.feed("[APPL]: Group ID: 0, Response Slot: 0, Status: 1",
                  "\tBASIC STATE",
                  "\t\tSynchronised:ON",
                  "\t\tService Needed:OFF")
        tag = self.tag(0, 10)
        self.assertEqual(tag.last_ping, "OK")
        self.assertEqual(tag.pings_sent, 1)
        self.assertEqual(tag.flags, {"Synchronised": True, "Service Needed": False})

    def test_ping_send_failure(self):
        self.c.ping(1, 2)
        self.feed("Failed to ping ESL: 0x0106",
                  "[APPL]: ESL AP send ping failed- retval 0x0106")
        self.assertEqual(self.tag(1, 2).last_ping, "Send failed 0x0106")

    def test_ping_timeout(self):
        self.c.ping(0, 1)
        self.c._pending_pings[0].sent_at -= ctl.PING_TIMEOUT_S + 1
        self.c._expire_pings()
        self.assertEqual(self.tag(0, 1).last_ping, "No response")

    def test_reboot_clears_tags(self):
        self.feed("[APPL]: ESL tag [0 : 0] synchronized (status 0x0000)",
                  "*** Booting Zephyr OS build v3.7.0 ***")
        self.assertEqual(self.c.tags.rowCount(), 0)


if __name__ == "__main__":
    unittest.main()
