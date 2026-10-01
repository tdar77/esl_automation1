"""Controller tests: replay console lines without a serial port.

Needs PyQt6 (skipped otherwise). Runs headless via QT_QPA_PLATFORM=offscreen.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    from esl_gui import controller as ctl
except ImportError:  # pragma: no cover
    ctl = None


@unittest.skipIf(ctl is None, "PyQt6 not installed")
class ControllerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
        self.assertEqual(self.sent, ["esl_ap auto 2 0"])
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

    def test_stop_mid_run(self):
        status = []
        self.c.auto_status_changed.connect(status.append)
        self.feed("ESL AP automation started",
                  "[APPL_AUTO]: ESL tag [0:0] added, connecting")
        self.c.stop_auto()
        self.assertEqual(self.sent, ["esl_ap auto_stop"])
        self.assertEqual(status[-1], "Stop requested…")
        self.assertTrue(self.c.auto_running)  # current tag is still finishing
        self.feed("[APPL_AUTO]: stop requested - finishing current tag",
                  "[APPL]: ESL tag [0 : 0] synchronized (status 0x0000)",
                  "[APPL_AUTO]: 1/4 tags synced",
                  "[APPL_AUTO]: batch finished - synced tags retained")
        self.assertFalse(self.c.auto_running)

    def test_stop_when_gui_missed_start(self):
        # GUI attached mid-run: no "automation started" line was seen.
        self.feed("[APPL_AUTO]: ESL tag [0:2] added, connecting")
        self.assertTrue(self.c.auto_running)
        self.c.stop_auto()
        self.assertEqual(self.sent, ["esl_ap auto_stop"])

    def test_stop_when_idle_still_sends(self):
        self.c.stop_auto()
        self.assertEqual(self.sent, ["esl_ap auto_stop"])
        self.feed("[APPL_AUTO]: esl_ap auto_stop - state reset to IDLE")
        self.assertFalse(self.c.auto_running)

    def at(self, t, *lines):
        """Feed lines as if they arrived at clock time t (seconds)."""
        self.c.clock = lambda: t
        self.feed(*lines)

    def test_sync_timing(self):
        timed = []
        self.c.sync_timed.connect(lambda *a: timed.append(a))
        self.at(0.0, "ESL AP automation started")
        self.at(1.5, "[APPL_AUTO]: ESL tag [0:0] added, connecting")
        self.at(4.0, "[APPL]: ESL tag [0 : 0] synchronized (status 0x0000)",
                "[APPL_AUTO]: 1/2 tags synced")
        self.at(6.0, "[APPL_AUTO]: ESL tag [0:1] added, connecting")
        self.at(9.5, "[APPL]: ESL tag [0 : 1] synchronized (status 0x0000)")

        self.assertEqual(timed, [(0, 0, 1.5, 2.5), (0, 1, 2.0, 3.5)])
        self.assertEqual((self.tag(0, 0).scan_s, self.tag(0, 0).sync_s), (1.5, 2.5))
        self.assertEqual((self.tag(0, 1).scan_s, self.tag(0, 1).sync_s), (2.0, 3.5))

    def test_failed_sync_not_timed(self):
        timed = []
        self.c.sync_timed.connect(lambda *a: timed.append(a))
        self.at(0.0, "ESL AP automation started",
                "[APPL_AUTO]: ESL tag [0:0] added, connecting")
        self.at(3.0, "[APPL]: ESL tag [0 : 0] synchronized (status 0x0101)",
                "[APPL_AUTO]: ESL tag [0:0] sync failed (status 0x0101)")
        self.assertEqual(timed, [])

    def test_manual_sync_has_no_timing(self):
        # sync_esl typed in the console: no 'added' line, so nothing to time from.
        self.at(5.0, "[APPL]: ESL tag [0 : 3] synchronized (status 0x0000)")
        self.assertIsNone(self.tag(0, 3).sync_s)
        self.assertIsNotNone(self.tag(0, 3).synced_at)

    def test_auto_into_group(self):
        groups, status = [], []
        self.c.auto_group.connect(groups.append)
        self.c.auto_status_changed.connect(status.append)
        self.c.start_auto(3, 2)
        self.assertEqual(self.sent, ["esl_ap auto 3 2"])
        self.feed("[APPL_AUTO]: esl_ap auto requested (target 3 tags, next [2:0]) - init + scan",
                  "ESL AP automation started")
        self.assertEqual(groups, [2])
        self.assertEqual(status[-1], "Scanning for tags (group 2)…")

    def test_console_run_reports_group(self):
        groups = []
        self.c.auto_group.connect(groups.append)
        self.feed("uart:~$ esl_ap auto 2 1",
                  "[APPL_AUTO]: esl_ap auto requested (target 2 tags, next [1:4]) - init + scan")
        self.assertEqual(groups, [1])

    def test_specific_start_error_not_overwritten(self):
        status = []
        self.c.auto_status_changed.connect(status.append)
        self.c.start_auto(5, 1)
        self.feed("[APPL_AUTO]: Cannot add 5 tags to group 1: only 3 of 16 response slots free",
                  "Invalid group or too many tags for the free response slots in that group.")
        self.assertEqual(status[-1], "Error: Cannot add 5 tags to group 1: only 3 of 16 "
                                     "response slots free")

    def test_generic_start_error_shown_alone(self):
        # APPL_ESL_ERR can be compiled out; the CLI line must still surface.
        status = []
        self.c.auto_status_changed.connect(status.append)
        self.c.start_auto(5, 1)
        self.feed("Invalid group or too many tags for the free response slots in that group.")
        self.assertTrue(status[-1].startswith("Error: Invalid group or too many tags"))

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
